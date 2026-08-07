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

### Air Quality Overlay

The `mg` camera's GNPC feed carries an air quality badge: a severity dot colored by US EPA AQI category next to the AQI for the [Many Glacier Ranger Station](https://map.purpleair.com/) PurpleAir sensor's 10-minute average PM2.5. The NPS feed of the same camera deliberately does not get it.

```yaml
- type: air_quality
  sensor_index: 111457   # PurpleAir "Many Glacier Ranger Station"
```

Useful options: `metric: pm25` (with `label: PM2.5`) shows the raw concentration instead of the AQI, `place: [x, y]` overrides the auto top-right corner, and `cache_seconds` / `max_reading_age` control how often the API is queried and how stale a sensor may be before the badge is dropped. Every failure mode — missing `PURPLE_KEY`, a failed request, a sensor that has gone quiet — publishes the image without the badge rather than a wrong number.

Readings are cached in the system temp directory (`gnpc-purpleair-<sensor_index>.json`) so the once-a-minute cron cadence doesn't re-query the API for data that only changes every couple of minutes. The cache is disposable; deleting it just forces a fresh fetch.

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

## File Structure

```
overlays/          # Logo images and graphics
fonts/             # Font files for timestamp rendering
webcams.yaml       # All webcam and overlay configurations
config.py          # Configuration dataclasses and YAML loading
environment.env    # Credentials and settings (not in repo)
tests/             # Unit tests (pytest) and manual debug scripts
```
