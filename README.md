# GNPC Webcams Operation

Automated webcam image and video processing system for the Glacier National Park Conservancy. Downloads webcam images from glacier.org FTP (and, for Two Medicine and St. Mary, from the NPS webcam page), applies GNPC logos with custom positioning, adds professional timestamps, and uploads processed images to an HTML server for public viewing.

## Architecture

The system consists of seven main classes:

- **`Webcam`** - Main image processing class handling FTP download, logo application, timestamp overlay, and upload
- **`HttpWebcam`** - A `Webcam` whose source frame is fetched from a URL instead of the FTP server; everything after the download is inherited unchanged
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

Each entry in `logo_placements` produces one published image; `subname` is appended to the output filename (e.g. `lpp_nps.jpg`). The published name comes from `name`, so `- name: lpp` uploads `lpp.jpg`. Setting `blackout: true` on a webcam publishes plain black frames in place of the feed (used when a camera is misaimed).

### Image Sources

A webcam draws its frame from exactly one source — the loader rejects an entry that gives both or neither:

| key | source |
|---|---|
| `file_name_on_server` | a file on the glacier.org FTP server, timestamped from its `MDTM` reply |
| `url` | an HTTP(S) URL, timestamped from the response's `Last-Modified` header |

`tm` (Two Medicine) and `stmary` (St. Mary, looking up the valley from the visitor center) are the URL-sourced cameras. Neither feeds into the glacier.org FTP server, so both are fetched from the NPS webcam page with NPS's permission and republished with GNPC branding. NPS burns its own caption and timestamp into the top edge of those frames, so both leave `cover_date` off rather than stamping a second date. A URL-sourced camera is otherwise configured, overlaid and uploaded exactly like an FTP one.

```yaml
- name: tm
  url: https://www.nps.gov/webcams-glac/TwoMedicine.jpg

- name: stmary
  url: https://www.nps.gov/webcams-glac/StMaryPTZ.jpg
```

Each publishes a single image. NPS hosts the originals, so an `_nps` variant of either would have no consumer. Note that `stmary` and `smv` are different cameras pointed at the same valley from opposite ends — `smv` looks down it from Logan Pass.

### Overlay Types

- **Single overlays**: Apply one `logo`, `temperature` or `air_quality` overlay
- **Composite overlays**: Nest overlays in a list to combine them into one image (see `webcams-temperature.yaml` for a logo + temperature example)
- **Auto-positioning**: Temperature and air quality overlays can auto-position to the top-right corner

A placement list may not mix bare overlays with nested groups — if any placement is a group, wrap them all, as `mg` and `smv` do.

### Why the NPS feeds put the logo at x=185

The `subname: nps` variants exist because nps.gov displays our frames cropped. Its webcam index uses `object-fit: cover` in a box of roughly 1.43:1, so a 16:9 frame loses the difference off both sides: 189 px per side at the widest layout, growing to about 205 px on a narrow phone. The logo starts at 185 so its shading still runs to the visible edge at every width — shading hidden under the crop costs nothing, whereas a gap between the crop edge and the logo is immediately obvious.

The click-through page (`/media/webcam/view.htm`) uses `object-fit: fill` and shows the whole frame, so the same logo reads as inset there. No single x is flush in both; the index wins because that is the page people browse.

NPS has changed this crop more than once, so re-measure rather than assume. In the browser console on their webcams page:

```js
document.querySelectorAll('img.WebcamPreview__CoverImage').forEach(i => {
  const r = i.getBoundingClientRect();
  const s = Math.max(r.width / i.naturalWidth, r.height / i.naturalHeight);
  console.log(i.src.split('/').pop(),
              'crop per side:', Math.round((i.naturalWidth * s - r.width) / s / 2), 'px');
});
```

`dark_sky_nps` is exempt: that frame is 1021×687, close enough to the box aspect that it loses only 25 px per side, and its NPS variant is offset vertically (`604` against the GNPC feed's `619`) rather than horizontally.

### Conditions Badge (Air Quality + Temperature)

Six feeds carry a conditions badge in the bottom-right corner: temperature above a hairline, then a severity dot colored by US EPA AQI category, the AQI from a [PurpleAir](https://map.purpleair.com/) sensor, and the category wording. Each reads the sensor nearest its own camera, so the number is local rather than borrowed:

| feed | sensor | note |
|---|---|---|
| `mg` | 111457 "Many Glacier Ranger Station" | GNPC feed only; the NPS feed of the same camera deliberately has no badge |
| `lpp`, `hlt`, `smv` | 192039 "Logan Pass" | the three Logan Pass cameras share one sensor at the visitor center; GNPC feeds only |
| `tm` | 192041 "Two Medicine" | 0.1 mi from the camera |
| `stmary` | 83937 "St. Mary - Visitor Center" | AQI only — see below |

```yaml
- type: air_quality
  sensor_index: 111457
```

The `dark_sky` allsky feed deliberately has no badge. A fisheye of the sky is the one view where a conditions readout adds nothing anybody came for.

The St. Mary sensor reports PM2.5 but no temperature and no humidity — that module is dead or absent — so its badge collapses to the AQI-only pill and the EPA correction falls back to its RH 50 default. It carries `show_temperature: false`, which stops paying 2 points a call for a field that always comes back null. That is the one setting to remove if the module is ever repaired; until then the badge would look identical either way, so nothing but the bill changes.

It sits bottom-right on purpose. On `mg` the lake surface is the only large region of the frame that carries no information, so the badge hides nothing there and balances the Conservancy logo across the bottom edge; the top-right corner covered the ridgeline. The same corner works on `tm` and `stmary` — treetops and foreground grass — while their top-right is where the mountains sit. `anchor` takes any of `bottom-right` (default), `bottom-left`, `top-right`, `top-left`.

#### Layout collapse

Temperature and AQI come from measurements that can fail independently, so the badge picks its shape from what actually arrived:

| available | shape |
|---|---|
| both | square tile, temperature over AQI |
| AQI only | horizontal pill, dot + AQI + category |
| temperature only | horizontal pill, temperature alone (no dot — the dot means AQI severity) |
| neither | no badge; the frame publishes untouched |

#### Temperature

The temperature comes from the same PurpleAir sensor, which at Many Glacier is the only instrument physically on site. Its thermometer sits inside the enclosure where the electronics and sunlight both warm it, so the reading runs hot; `temperature_offset` (default `-8.0` °F) is PurpleAir's own published correction, which keeps the badge agreeing with what purpleair.com shows for the sensor. Note that [published evaluations](https://www.mdpi.com/2073-4433/15/4/415) find this correction tends to overcorrect, with real bias averaging nearer 2.6 °C — so treat the number as approximate and adjust `temperature_offset` if it drifts from reality.

Setting `temperature_source: endpoint` reads `temperature_endpoint` (a plaintext HTTP endpoint) instead, and `show_temperature: false` drops temperature entirely, which also stops paying for the field.

#### EPA correction

By default the reading is not published raw. PurpleAir's low-cost sensors disagree with reference monitors in a well-characterized way, so the overlay applies the EPA's extended US-wide correction (Barkjohn et al. 2021, extended in 2022 for wildfire concentrations) — the same correction AirNow applies to PurpleAir data on its Fire and Smoke Map. Set `conversion: none` to publish the sensor's own number instead.

The correction is defined against the sensor's CF=1 channel, but the API only publishes 10-minute averages of the ATM channel. The two channels track each other by a concentration-dependent ratio (identical in clean air, roughly 3:2 in smoke), so the overlay scales the 10-minute average by the sensor's current CF=1-to-ATM ratio before correcting. The ratio is clamped to 1.0–1.6 so one noisy instantaneous sample can't distort the published number.

The correction moves in both directions: it lowers the number in clean air and raises it in smoke. It is not cosmetic — during the August 2026 smoke it was the difference between AQI 226 and 263.

#### Other options

`metric: pm25` (with `label: PM2.5`) shows the concentration instead of the AQI, `show_category: false` drops the wording and shrinks the badge to one line, `place: [x, y]` overrides the auto top-right corner, and `cache_seconds` / `max_reading_age` control how often the API is queried and how stale a sensor may be before the badge is dropped. Every failure mode — missing `PURPLE_KEY`, a failed request, a sensor that has gone quiet — publishes the image without the badge rather than a wrong number.

Readings are cached for 10 minutes in the system temp directory (`gnpc-purpleair-<sensor_index>.json`), matching the averaging window, so the once-a-minute cron cadence doesn't re-query the API for data that hasn't changed. The cache is disposable; deleting it just forces a fresh fetch.

#### API point cost

PurpleAir bills per call as `base_cost + (cost_of_all_fields × rows)`. A single-sensor query is one row with a base of 1 point, so a call costs **8 points** where the badge shows temperature and **6 points** where it doesn't:

| field | points | why it can't be dropped |
|---|---|---|
| `pm2.5_10minute` | 2 | the reading itself |
| `pm2.5_cf_1` | 2 | numerator of the ATM→CF=1 ratio |
| `humidity_a` | 1 | input to the EPA correction |
| `temperature` | 2 | the badge's temperature (drop with `show_temperature: false`) |

Humidity is bought per channel on purpose: `humidity_a` costs 1 point where the A/B average `humidity` costs 2, and these sensors carry a humidity module on channel A only, so the two return the same number. Even on a two-module sensor the channels would have to disagree by about 12 %RH to shift the corrected PM2.5 by a single microgram.

Querying the sensors one at a time is the cheap way round, despite appearances. Batching them into one `GET /v1/sensors` call loses on both terms of the formula: that endpoint's base cost is 5 points against the single-sensor endpoint's 1, and it returns only the flat columns you pay for — no `stats` block — so the two values below that currently arrive free would have to be bought as fields. For three sensors that is 5 + 12×3 = 41 points a cycle against the 22 the three separate calls cost. Batching only wins for callers who omit `fields` entirely and get billed for every one.

Three other values arrive **free** inside the `stats` block that comes with `pm2.5_10minute`, so they must not be requested as fields: `stats.pm2.5` (the current ATM reading, rounded — the ratio's denominator, making `pm2.5_atm` redundant), and `stats.time_stamp` (identical to `last_seen`, used for the staleness check). Adding either back costs 2 points a call for nothing.

Each sensor is queried and cached separately, so cost scales with sensors, not feeds: at the 10-minute cache cadence the three badges cost 22 points a cycle — 8 each for Many Glacier and Two Medicine, 6 for St. Mary — or ~3,170 points/day, roughly $0.95/month at $1 per 100,000 points. Setting `conversion: none` would drop the query to one field and 3 points, but that trades away the correction — not worth it. `GET /v1/organization` reports the remaining balance and is free to poll.

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

The system processes 7 webcam images and 1 overnight timelapse video using threading for parallel processing, with automatic retry logic for both FTP and HTTP downloads and comprehensive logging. FTP connections use FTPS when the server supports it, falling back to plain FTP. All file paths resolve relative to the repository directory, so the cron `cd` is optional.

## Testing

```bash
uv run pytest
```

Unit tests in `tests/` cover config parsing, overlay composition and download retries without touching the network. `tests/manual/` holds standalone debug scripts that do hit the live sources; run them directly with Python when needed. `preview_feeds.py <camera>` is the usual one — it downloads a camera's current frame, applies its real overlays, and writes every published feed to `debug-images/` without uploading anything.

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
