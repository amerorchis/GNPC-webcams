# GNPC Webcams Operation

Automated webcam image and video processing system for the Glacier National Park Conservancy. Downloads webcam images from glacier.org FTP, applies GNPC logos with custom positioning, adds professional timestamps, and uploads processed images to an HTML server for public viewing.

## Architecture

The system consists of six main classes:

- **`Webcam`** - Main image processing class handling FTP download, logo application, timestamp overlay, and upload
- **`Logo`** - Encapsulates logo placement configuration with custom positioning and sizing  
- **`Temperature`** - Fetches and overlays temperature data with customizable styling
- **`AirQuality`** - Fetches a PurpleAir sensor reading and overlays an AQI badge
- **`CompositeOverlay`** - Combines multiple overlays (logo + temperature) into single composite images
- **`AllskyVideo`** - Inherits from Webcam for overnight timelapse video processing using FFmpeg

## Configuration

All webcam configurations are defined in `webcams.yaml` using dataclasses for type safety:

```yaml
webcams:
  - name: lpp
    file_name_on_server: lpp.jpg
    logo_placements:
      - type: logo
        place: [140, 944]
        size: [612, 137]
        img: overlays/logo-shaded.png
        subname: nps
      - type: logo
        place: [0, 944]
        size: [612, 137]
        img: overlays/logo-shaded.png
```

Each entry in `logo_placements` produces one published image; `subname` is appended to the output filename (e.g. `lpp_nps.jpg`). Setting `blackout: true` on a webcam publishes plain black frames in place of the feed (used when a camera is misaimed).

### Overlay Types

- **Single overlays**: Apply one `logo`, `temperature` or `air_quality` overlay
- **Composite overlays**: Nest overlays in a list to combine them into one image (see `webcams-temperature.yaml` for a logo + temperature example)
- **Auto-positioning**: Temperature and air quality overlays can auto-position to the top-right corner

A placement list may not mix bare overlays with nested groups — if any placement is a group, wrap them all, as `mg` and `smv` do.

### Conditions Badge (Air Quality + Temperature)

The `mg` camera's GNPC feed carries a conditions badge in the bottom-right corner: temperature above a hairline, then a severity dot colored by US EPA AQI category, the AQI for the [Many Glacier Ranger Station](https://map.purpleair.com/) PurpleAir sensor, and the category wording. The NPS feed of the same camera deliberately does not get it.

```yaml
- type: air_quality
  sensor_index: 111457   # PurpleAir "Many Glacier Ranger Station"
```

It sits bottom-right on purpose. The lake surface is the only large region of the frame that carries no information, so the badge hides nothing there and balances the Conservancy logo across the bottom edge; the top-right corner covered the ridgeline. `anchor` takes any of `bottom-right` (default), `bottom-left`, `top-right`, `top-left`.

#### Layout collapse

Temperature and AQI come from measurements that can fail independently, so the badge picks its shape from what actually arrived:

| available | shape |
|---|---|
| both | square tile, temperature over AQI |
| AQI only | horizontal pill, dot + AQI + category |
| temperature only | horizontal pill, temperature alone (no dot — the dot means AQI severity) |
| neither | no badge; the frame publishes untouched |

#### Temperature

The temperature comes from the PurpleAir sensor, which is the only instrument physically at Many Glacier. Its thermometer sits inside the enclosure where the electronics and sunlight both warm it, so the reading runs hot; `temperature_offset` (default `-8.0` °F) is PurpleAir's own published correction, which keeps the badge agreeing with what purpleair.com shows for the sensor. Note that [published evaluations](https://www.mdpi.com/2073-4433/15/4/415) find this correction tends to overcorrect, with real bias averaging nearer 2.6 °C — so treat the number as approximate and adjust `temperature_offset` if it drifts from reality.

Setting `temperature_source: endpoint` reads `temperature_endpoint` (a plaintext HTTP endpoint) instead, and `show_temperature: false` drops temperature entirely, which also stops paying for the field.

#### EPA correction

By default the reading is not published raw. PurpleAir's low-cost sensors disagree with reference monitors in a well-characterized way, so the overlay applies the EPA's extended US-wide correction (Barkjohn et al. 2021, extended in 2022 for wildfire concentrations) — the same correction AirNow applies to PurpleAir data on its Fire and Smoke Map. Set `conversion: none` to publish the sensor's own number instead.

The correction is defined against the sensor's CF=1 channel, but the API only publishes 10-minute averages of the ATM channel. The two channels track each other by a concentration-dependent ratio (identical in clean air, roughly 3:2 in smoke), so the overlay scales the 10-minute average by the sensor's current CF=1-to-ATM ratio before correcting. The ratio is clamped to 1.0–1.6 so one noisy instantaneous sample can't distort the published number.

The correction moves in both directions: it lowers the number in clean air and raises it in smoke. It is not cosmetic — during the August 2026 smoke it was the difference between AQI 226 and 263.

#### Other options

`metric: pm25` (with `label: PM2.5`) shows the concentration instead of the AQI, `show_category: false` drops the wording and shrinks the badge to one line, `place: [x, y]` overrides the auto top-right corner, and `cache_seconds` / `max_reading_age` control how often the API is queried and how stale a sensor may be before the badge is dropped. Every failure mode — missing `PURPLE_KEY`, a failed request, a sensor that has gone quiet — publishes the image without the badge rather than a wrong number.

Readings are cached for 10 minutes in the system temp directory (`gnpc-purpleair-<sensor_index>.json`), matching the averaging window, so the once-a-minute cron cadence doesn't re-query the API for data that hasn't changed. The cache is disposable; deleting it just forces a fresh fetch.

#### API point cost

PurpleAir bills per call as `base_cost + (cost_of_all_fields × rows)`. A single-sensor query is one row with a base of 1 point, and the fields this overlay needs cost 2 points each, so a call costs **9 points**:

| field | why it can't be dropped |
|---|---|
| `pm2.5_10minute` | the reading itself |
| `pm2.5_cf_1` | numerator of the ATM→CF=1 ratio |
| `humidity` | input to the EPA correction |
| `temperature` | the badge's temperature (drop with `show_temperature: false`) |

Three other values arrive **free** inside the `stats` block that comes with `pm2.5_10minute`, so they must not be requested as fields: `stats.pm2.5` (the current ATM reading, rounded — the ratio's denominator, making `pm2.5_atm` redundant), and `stats.time_stamp` (identical to `last_seen`, used for the staleness check). Adding either back costs 2 points a call for nothing.

At the 10-minute cache cadence that's ~1,300 points/day, or roughly $0.39/month at $1 per 100,000 points. Setting `conversion: none` would drop the query to one field and 3 points, but that trades away the correction — not worth it. `GET /v1/organization` reports the remaining balance and is free to poll.

## Environment Setup

1. Copy `template.env` to `environment.env` and configure:
   - FTP credentials for glacier.org server
   - HTML server upload credentials  
   - `PURPLE_KEY`, a PurpleAir read key, for the air quality overlay
   - `LOG_LEVEL=INFO` for development, `LOG_LEVEL=WARN` for production

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Ensure FFmpeg is installed system-wide for video processing

## Operation

**Development:**
```bash
python main.py
```

**Production (cron):**
```bash
* * * * * cd /path/to/GNPC-webcams && .venv/bin/python main.py >/dev/null
```

Errors are printed to stderr so cron emails them even with stdout discarded. The production `.venv` is built with `uv sync --no-dev` from `uv.lock`; cron invokes the venv's interpreter directly, so uv itself is only needed when setting up or updating dependencies.

Only one run executes at a time. A run holds an exclusive `flock` on `webcams.lock` for its duration; if a slow run is still going when cron fires the next minute, that run logs a skip and exits without touching FTP. This keeps stacked runs from exhausting the server's per-IP connection limit (`421 Too many connections`). The lock is held by the process, so a killed or crashed run releases it automatically — a leftover `webcams.lock` file is normal and never needs to be deleted by hand.

The system processes 5 webcam images and 1 overnight timelapse video using threading for parallel processing, with automatic retry logic for FTP operations and comprehensive logging. Connections use FTPS when the server supports it, falling back to plain FTP. All file paths resolve relative to the repository directory, so the cron `cd` is optional.

## Testing

```bash
uv run pytest
```

Unit tests in `tests/` cover config parsing and overlay composition without touching the network. `tests/manual/` holds standalone debug scripts that hit the live FTP server; run them directly with Python when needed.

## Deployment

Pushing to `main` deploys to the production Pi; no manual SSH or `git pull` is needed. `.github/workflows/ci.yml` defines both halves:

1. **Lint and test** runs on a GitHub-hosted runner for every push and pull request — `ruff check`, `ruff format --check`, and `pytest`. The ruff version is pinned to match `.pre-commit-config.yaml` so CI and the pre-commit hook agree. Font-dependent tests skip themselves, since fonts are untracked.
2. **Deploy to gnpic** runs `scripts/deploy.sh` on a self-hosted runner on the Pi, but only after the tests pass and only for a push to `main` (or a manual `workflow_dispatch`). Pull requests, including any from a fork of this public repo, cannot reach the Pi.

`scripts/deploy.sh` takes the same `webcams.lock` that a run holds before it touches anything, so a deploy waits for the current run to finish instead of swapping files underneath it; the run that fires meanwhile simply skips its cycle. It fast-forwards rather than resetting, which both leaves untracked local state (`environment.env`, `.python-version`, `fonts/`, `images/`, logs) alone and stops loudly if the Pi has picked up local commits. Dependencies re-sync only when `pyproject.toml` or `uv.lock` changed, using the interpreter already in `.venv` — uv's managed ARM builds segfault on this Pi. Finally it imports `main`, which builds every camera from `webcams.yaml` without touching the network; if that fails the checkout is rolled back and the run goes red.

To deploy without a commit, use **Actions → CI → Run workflow** on `main`.

The runner is a systemd service on the Pi, installed in `~/actions-runner-gnpc-webcams`:

```bash
cd ~/actions-runner-gnpc-webcams && sudo ./svc.sh status   # or stop / start
```

> **Note:** GitHub is dropping support for Linux ARM32 self-hosted runners after 16 September 2026. This Pi runs a 32-bit (`armhf`) userland, so the deploy job will stop working then and will need either a 64-bit OS on the Pi or a switch to an SSH-based deploy over Tailscale.

## File Structure

```
overlays/          # Logo images and graphics
fonts/             # Font files for timestamp rendering
webcams.yaml       # All webcam and overlay configurations
config.py          # Configuration dataclasses and YAML loading
environment.env    # Credentials and settings (not in repo)
tests/             # Unit tests (pytest) and manual debug scripts
scripts/deploy.sh  # Updates the production checkout on the Pi
.github/workflows/ # CI checks and deployment
```
