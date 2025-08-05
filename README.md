# GNPC Webcams Operation

Automated webcam image and video processing system for the Glacier National Park Conservancy. Downloads webcam images from glacier.org FTP, applies GNPC logos with custom positioning, adds professional timestamps, and uploads processed images to an HTML server for public viewing.

## Architecture

The system consists of five main classes:

- **`Webcam`** - Main image processing class handling FTP download, logo application, timestamp overlay, and upload
- **`Logo`** - Encapsulates logo placement configuration with custom positioning and sizing  
- **`Temperature`** - Fetches and overlays temperature data with customizable styling
- **`CompositeOverlay`** - Combines multiple overlays (logo + temperature) into single composite images
- **`AllskyVideo`** - Inherits from Webcam for overnight timelapse video processing using FFmpeg

## Configuration

All webcam configurations are defined in `webcams.yaml` using dataclasses for type safety:

```yaml
webcams:
  - name: lpp
    file_name_on_server: lpp.jpg
    logo_placements:
      # Composite overlay: logo + temperature
      - - type: logo
          place: [1507, 10]
          size: [531, 88]
          img: overlays/logo.png
          subname: nps
        - type: temperature
          place: [0, 54]
          size: [175, 66]
          endpoint: "https://glacier.org/scripts/post_temp.cgi"
          subname: nps
```

### Overlay Types

- **Single overlays**: Apply one logo or temperature overlay
- **Composite overlays**: Apply multiple overlays in sequence to create combined images
- **Auto-positioning**: Temperature overlays can auto-position to top-right corner

## Environment Setup

1. Copy `template.env` to `environment.env` and configure:
   - FTP credentials for glacier.org server
   - HTML server upload credentials  
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
* * * * * cd /path/to/GNPC-webcams && ./main.py
```

The system processes 6 webcam instances using threading for parallel processing, with automatic retry logic for FTP operations and comprehensive logging.

## File Structure

```
overlays/          # Logo images and graphics
fonts/             # Font files for timestamp rendering
webcams.yaml       # All webcam and overlay configurations
config.py          # Configuration dataclasses and YAML loading
environment.env    # Credentials and settings (not in repo)
```
