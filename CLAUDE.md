# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GNPC-webcams is an automated webcam image and video processing system for the Glacier National Park Conservancy. It downloads webcam images from glacier.org FTP (plus Two Medicine and St. Mary from the NPS webcam page), applies GNPC logos with custom positioning, adds professional timestamps, and uploads processed images to an HTML server for public viewing. The system also processes overnight timelapse videos with logo overlays.

## Core Architecture

The system consists of six main classes:

- **`Webcam`** - Main image processing class handling FTP download, logo application, timestamp overlay, and upload
- **`HttpWebcam`** - `Webcam` subclass that fetches its frame from a URL and takes the timestamp from the `Last-Modified` header; only the download differs. The fetch is conditional: the validators of the last *uploaded* frame live in the temp dir and a 304 sets `source_unchanged`, which makes `process()`/`upload_image()` no-ops for the round. A 200 whose body Pillow can't identify (nps.gov serves zero-byte files at times) is treated the same way, with its validators recorded so it isn't re-bought and reported every minute — one warning, not a traceback per run
- **`Logo`** - Encapsulates logo placement configuration with custom positioning and sizing
- **`AirQuality`** - Fetches a PurpleAir sensor's 10-minute PM2.5 average and temperature, applies the EPA's extended US-wide correction, and overlays a conditions badge (temperature over a severity dot + AQI + category wording). Collapses from a square to a single-value pill when only one measurement is available
- **`CompositeOverlay`** - Applies multiple overlays in sequence on one decoded image to produce one output image
- **`AllskyVideo`** - Inherits from Webcam for overnight timelapse video processing using FFmpeg

Main execution flow in `main.py` builds the cameras from `webcams.yaml` (currently 15 webcams plus 1 allsky video) and processes them in parallel threads. All file paths resolve relative to the repository directory via `paths.py`, so the working directory does not matter.

`Webcam`'s `_download_ftp`/`_upload_ftp` are one process-wide pool, so every assignment goes through `Webcam` rather than `cls`/`self.__class__` — a subclass attribute would shadow the pool and open a second session that `Webcam._close_connections()` never releases.

## Common Commands

**Running the application:**
```bash
# Direct execution (production method)
./main.py

# Using Python interpreter
python main.py
```

**Environment setup:**
```bash
# Create/update the uv-managed environment (.venv/)
uv sync

# The system expects environment.env file with FTP credentials
# Use template.env as reference
```

**Testing:**
```bash
# Unit tests (config parsing, overlay composition — no network)
uv run pytest

# Manual debug scripts that hit the live FTP server live in tests/manual/
```

## Development Environment

- **Python version**: 3.11 (uv-managed `.venv/` both locally and on the production Raspberry Pi, synced from uv.lock)
- **Key dependencies**: Pillow, ffmpeg-python, python-dotenv, PyYAML, requests (see pyproject.toml for versions)
- **External requirements**: FFmpeg binary must be installed system-wide
- **Fonts**: `fonts/OpenSans-Bold.ttf` (timestamps) and `fonts/SourceSansVariable-Bold.ttf` (badge) are vendored under the OFL so CI exercises the drawing code; the rest of `fonts/` is local-only

## Key Configuration

- Environment variables managed via `.env` files
- Logo variants: `logo.png`, `logo-shaded.png`, `logo-shaded-video.png`
- Multiple logo placements per image for different website contexts
- A placement list is either all bare overlays or all groups — `Webcam.__init__` decides from the first entry, so mixing the two forms silently breaks the rest
- Each webcam entry carries exactly one source: `file_name_on_server` (FTP) or `url` (HTTP, via `HttpWebcam`). `WebcamConfig.__post_init__` rejects both or neither
- `tm` (Two Medicine), `stmary` (St. Mary from the visitor center) and the eight west-side cameras (`apgar_mtn`, `apgar_village`, `lake_mcdonald`, `lake_mcdonald2`, `apgar_visitor_center`, `middle_fork`, `headquarters`, `west_entrance`) are republished from nps.gov with NPS's permission. NPS burns its own caption/timestamp into those frames, so none uses `cover_date`, and each publishes a single GNPC image — NPS hosts the originals, so an `_nps` variant would have no consumer
- The NPS-sourced frames come in three sizes: 1920x1080, 1280x720 and 1600x1200. The logo is placed proportionally in each (width 31.9% of the frame, bottom edge flush), so the 720p and 1200p feeds do not use the standard `[0, 944]` / `[612, 137]`. `apgar_mtn` refreshes far more slowly than the rest — an hours-old frame there is the camera, not the pipeline
- `stmary` and `smv` are different cameras: `smv` looks down the St. Mary valley from Logan Pass, `stmary` up it from the visitor center. `smv`'s blackout has nothing to do with `stmary`
- `PURPLE_KEY` (PurpleAir read key) drives the conditions badge on fourteen feeds — the GNPC feeds of `mg`, `lpp`, `smv` and `hlt`, plus `tm`, `stmary` and the eight west-side cameras — each from its nearest sensor. Three sensors are shared: 192039 by the Logan Pass cameras and 111211 by all eight west-side ones. Readings are cached per sensor in the system temp dir between cron runs, so a shared sensor is fetched once per run however many cameras use it. A feed can list `fallback_sensors` to try when its own sensor goes quiet — the west side falls back to 190835 ("Lake McDonald - Apgar"). A sensor that answers with nothing is cached as a miss for `miss_cache_seconds`, so a dead sensor is not re-bought by all eight cameras every minute
- The badge is measured in pixels of a 1920x1080 frame. Cameras with a different frame size set `scale` to their width over 1920 (the 1280x720 and 1600x1200 west-side feeds use 0.67 and 0.83), which shrinks the whole badge and its margin so it stays the same fraction of the picture. It folds into the existing 4x supersample, so a scaled badge is resampled once, not twice
- The `dark_sky` allsky feed has no badge by choice: a fisheye of the sky is the one view a conditions readout adds nothing to. Don't "restore" it
- PurpleAir sensor 83937 (St. Mary) reports no temperature or humidity, so `stmary`'s badge collapses to the AQI-only pill and the EPA correction uses its RH 50 fallback. It carries `show_temperature: false` so the null field isn't bought; remove that if the module is ever repaired
- The `subname: nps` logos sit at x=185 because nps.gov's index crops 189–205px off each side; the value has to stay at or below 189 so the logo's shading reaches the visible edge. See the README for how to re-measure when NPS restyles
- Humidity is bought as `humidity_a` (1 point), not `humidity` (2 points, the A/B average) — these sensors have a channel-A module only, so the values are identical. Batching sensors into `GET /v1/sensors` is more expensive, not less: base 5 vs 1, and no free `stats` block
- `AirQualityConfig`'s defaults are splatted into `AirQuality`, so every one must mirror the class — `test_air_quality_config_defaults_match_the_overlay` fails if they drift
- There is no physical temperature sensor at Many Glacier any more; the PurpleAir unit is the only local thermometer, and glacier.org's `post_temp.cgi` is not measured there
- Timestamps converted from UTC to Mountain Time (`Webcam.MOUNTAIN_TIME`) via zoneinfo; `AllskyVideo.check_if_processed_today` compares dates in that zone too
- Overlays implement `apply(image) -> image` on decoded pixels; the base `add_overlay` does the one JPEG encode at `Overlays.JPEG_QUALITY` (90). Don't save inside `apply` — a group would then be re-encoded per overlay

## Operational Notes

- Designed to run every minute via cron job
- Uses threading for parallel webcam processing
- Includes retry logic for FTP operations (6-second delays)
- Videos are automatically deleted after processing
- Error notifications sent via cron stdout/email
- FTP connections upgrade to FTPS when the server supports it, falling back to plain FTP

## Deployment

- A push to `main` deploys to the Pi automatically; nobody should be SSHing in to `git pull`
- `.github/workflows/ci.yml` runs ruff + pytest on a hosted runner, then `scripts/deploy.sh` on a self-hosted runner on the Pi. The deploy job requires a `push`/`workflow_dispatch` on `main`, which is what keeps fork pull requests off the Pi — the repo is public, so don't loosen that `if:` or add `pull_request_target`
- The ruff pin in the workflow must track the one in `.pre-commit-config.yaml`, or CI and the hook will disagree
- `scripts/deploy.sh` takes `webcams.lock` before touching the checkout, fast-forwards (never resets) so untracked Pi state survives, removes an untracked file only when the target commit tracks a byte-identical copy (refusing otherwise), syncs deps only when the lockfile moved, and rolls back if `import main` fails
- uv on the Pi must not fetch a managed ARM Python — those segfault. The deploy pins `UV_PYTHON` to the existing `.venv` interpreter and sets `UV_PYTHON_DOWNLOADS=never`
- GitHub drops Linux ARM32 self-hosted runners after 2026-09-16. This Pi is `armhf`, so the deploy job needs a 64-bit OS or an SSH-based deploy before then

## Architecture Patterns

The codebase follows a class-based approach where `Webcam` handles core functionality and `AllskyVideo` extends it for video-specific operations. Logo placement is abstracted into a separate `Logo` class to handle different positioning requirements for various website crop contexts.