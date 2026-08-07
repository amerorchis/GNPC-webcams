"""
Overlay classes for webcam image processing.
"""

import io
import json
import logging
import math
import os
import random
import tempfile
import threading
import time
from abc import ABC, abstractmethod

import requests
from PIL import Image, ImageDraw, ImageFont

from paths import resolve_path

logger = logging.getLogger(__name__)


class Overlay(ABC):
    """Abstract base class for image overlays."""

    def __init__(self, place, size, subname=None):
        self.place = place
        self.size = size
        self.subname = subname
        self.overlayed = io.BytesIO()

    @abstractmethod
    def add_overlay(self, image, mod_time_str=""):
        """Apply the overlay to the image. Must be implemented by subclasses."""
        pass

    def get_overlayed_img(self, name):
        """Get the overlayed image with appropriate filename."""
        name += f"_{self.subname}.jpg" if self.subname else ".jpg"
        return self.overlayed, name


class Logo(Overlay):
    def __init__(
        self,
        place,
        size,
        img="overlays/logo-shaded.png",
        subname=None,
        cover_date=False,
        cover_date_img="overlays/corner-rectangle.png",
        cover_date_bg_color=None,
        cover_date_size=None,
        cover_date_position=(0, 0),
        cover_date_font_path="fonts/OpenSans-Bold.ttf",
        cover_date_font_size=16,
        cover_date_text_position=(4, 3),
        cover_date_text_color=(255, 255, 255),
        cover_date_text_scale=1.0,
    ):
        super().__init__(place, size, subname)
        self.logo_img = img
        self.cover_date = cover_date
        self.cover_date_img = cover_date_img
        self.cover_date_bg_color = cover_date_bg_color
        self.cover_date_size = cover_date_size
        self.cover_date_position = cover_date_position
        self.cover_date_font_path = cover_date_font_path
        self.cover_date_font_size = cover_date_font_size
        self.cover_date_text_position = cover_date_text_position
        self.cover_date_text_color = cover_date_text_color
        self.cover_date_text_scale = cover_date_text_scale

    def add_overlay(self, image, mod_time_str=""):
        self.overlayed = io.BytesIO()

        # Open the images
        logo = Image.open(resolve_path(self.logo_img))
        webcam = Image.open(image)

        # Resize logo
        logo = logo.resize(self.size)

        # Create a copy of image
        webcam_and_logo = webcam.copy()

        # Paste logo onto cam at the specified location
        webcam_and_logo.paste(logo, self.place, logo)

        # Cover old datetime
        if self.cover_date:
            position = tuple(self.cover_date_position)
            if self.cover_date_bg_color is not None:
                cover = Image.new(
                    "RGBA", tuple(self.cover_date_size), tuple(self.cover_date_bg_color)
                )
            else:
                cover = Image.open(resolve_path(self.cover_date_img)).convert("RGBA")
            webcam_and_logo.paste(cover, position, cover)

            # Add datetime
            text_color = tuple(self.cover_date_text_color)
            text_xy = (
                position[0] + self.cover_date_text_position[0],
                position[1] + self.cover_date_text_position[1],
            )
            scale = self.cover_date_text_scale
            if scale and scale != 1.0 and self.cover_date_size is not None:
                # Render text on a downscaled transparent canvas, then upscale —
                # gives the text a softer/chunkier look matching JPEG camera output.
                cover_w, cover_h = self.cover_date_size
                small_w = max(1, int(round(cover_w * scale)))
                small_h = max(1, int(round(cover_h * scale)))
                small_font = ImageFont.truetype(
                    resolve_path(self.cover_date_font_path),
                    max(1, int(round(self.cover_date_font_size * scale))),
                )
                small_canvas = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
                small_draw = ImageDraw.Draw(small_canvas)
                small_draw.text(
                    (
                        int(round(self.cover_date_text_position[0] * scale)),
                        int(round(self.cover_date_text_position[1] * scale)),
                    ),
                    mod_time_str,
                    font=small_font,
                    fill=text_color,
                )
                upscaled = small_canvas.resize((cover_w, cover_h), Image.BILINEAR)
                webcam_and_logo.paste(upscaled, position, upscaled)
            else:
                draw = ImageDraw.Draw(webcam_and_logo)
                font = ImageFont.truetype(
                    resolve_path(self.cover_date_font_path), self.cover_date_font_size
                )
                draw.text(text_xy, mod_time_str, font=font, fill=text_color)

        # Save logoed file
        webcam_and_logo.save(self.overlayed, format="JPEG")
        self.overlayed.seek(0)


class Temperature(Overlay):
    """Temperature overlay that fetches temperature data from an endpoint."""

    def __init__(
        self,
        place=None,
        size=(175, 44),
        endpoint="https://glacier.org/scripts/post_temp.cgi",
        subname=None,
        font_path="fonts/SourceSansVariable-Bold.ttf",
        font_size=38,
        bg_color=(0, 0, 0, 64),
        bg_size=(175, 44),
        text_color=(255, 255, 255),
    ):
        # If place is not provided, it will be calculated in add_overlay
        # based on image dimensions
        super().__init__(
            place or (0, 0), size, subname
        )  # Use (0,0) temporarily if place is None
        self.place_auto = place is None  # Flag to indicate auto-positioning
        self.endpoint = endpoint
        self.font_path = font_path
        self.font_size = font_size
        self.bg_color = bg_color
        self.bg_size = bg_size
        self.text_color = text_color

    def fetch_temperature(self):
        """Fetch temperature from the endpoint."""
        try:
            # Headers to mimic a browser request
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0",
            }

            endpoint_cachebust = f"{self.endpoint}?rand={random.randint(1000, 9999)}"
            response = requests.get(endpoint_cachebust, headers=headers, timeout=10)
            response.raise_for_status()
            # Endpoint returns plaintext response
            temperature_raw = response.text.strip()
            if temperature_raw and temperature_raw != "N/A":
                return f"{temperature_raw} °F"
            else:
                return ""
        except requests.RequestException as e:
            logger.warning(f"Error fetching temperature: {e}")
            return ""

    def _load_bold_font(self):
        """Load font directly from the specified font path."""
        try:
            return ImageFont.truetype(resolve_path(self.font_path), self.font_size)
        except (OSError, IOError):
            # Fallback to default font if file not found
            return ImageFont.load_default()

    def add_overlay(self, image, mod_time_str=""):
        """Add temperature overlay to the image."""
        self.overlayed = io.BytesIO()

        # Open the webcam image
        webcam = Image.open(image)

        # Create a copy of the image
        webcam_with_temp = webcam.copy()

        # Calculate position if auto-positioning is enabled
        if self.place_auto:
            img_width, _ = webcam.size
            # Position so top-right corner of overlay is at top-right corner of image
            self.place = (img_width - self.bg_size[0], 0)

        # Fetch temperature data
        temperature_text = self.fetch_temperature()

        if not temperature_text:
            # No temperature data - save original image and return
            webcam_with_temp.save(self.overlayed, format="JPEG")
            self.overlayed.seek(0)
            return

        # Load font with bold weight if possible
        try:
            font = self._load_bold_font()
        except (OSError, IOError):
            font = ImageFont.load_default()

        # Use fixed background size
        actual_bg_size = self.bg_size

        # Create background rectangle
        background = Image.new("RGBA", actual_bg_size, self.bg_color)

        # Create text overlay
        text_overlay = Image.new("RGBA", actual_bg_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_overlay)

        # Calculate text dimensions to center it in the box
        text_bbox = draw.textbbox((0, 0), temperature_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Center text horizontally, shift up vertically
        text_x = (actual_bg_size[0] - text_width) // 2
        text_y = (actual_bg_size[1] - text_height) // 2 - 10

        # Draw text on the text overlay
        draw.text((text_x, text_y), temperature_text, font=font, fill=self.text_color)

        # Composite background and text
        final_overlay = Image.alpha_composite(background, text_overlay)

        # Paste the temperature overlay onto the webcam image
        webcam_with_temp.paste(final_overlay, self.place, final_overlay)

        # Save the overlayed file
        webcam_with_temp.save(self.overlayed, format="JPEG")
        self.overlayed.seek(0)


PURPLE_AIR_SENSOR_URL = "https://api.purpleair.com/v1/sensors/{sensor_index}"

# US EPA AQI breakpoints for PM2.5, revised May 2024:
# (concentration low, concentration high, AQI low, AQI high)
US_AQI_BREAKPOINTS = (
    (0.0, 9.0, 0, 50),
    (9.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 125.4, 151, 200),
    (125.5, 225.4, 201, 300),
    (225.5, 325.4, 301, 500),
)

# Official AQI category colors, keyed by the top of each category.
AQI_CATEGORY_COLORS = (
    (50, (0, 228, 0)),  # Good
    (100, (255, 255, 0)),  # Moderate
    (150, (255, 126, 0)),  # Unhealthy for sensitive groups
    (200, (255, 0, 0)),  # Unhealthy
    (300, (143, 63, 151)),  # Very unhealthy
    (500, (126, 0, 35)),  # Hazardous
)

# One cached PurpleAir reading per sensor, shared by every thread in the run and
# by consecutive cron runs (the file outlives the process). Sensors report every
# couple of minutes, so re-querying once per camera per minute would spend API
# points on data that has not changed.
_purple_air_cache_lock = threading.Lock()


def pm25_to_aqi(pm25):
    """Convert a PM2.5 concentration (µg/m³) to a US EPA AQI value."""
    # The EPA formula operates on the concentration truncated to one decimal.
    pm25 = math.floor(max(pm25, 0.0) * 10) / 10

    for conc_low, conc_high, aqi_low, aqi_high in US_AQI_BREAKPOINTS:
        if pm25 <= conc_high:
            scale = (aqi_high - aqi_low) / (conc_high - conc_low)
            return round(aqi_low + scale * (pm25 - conc_low))

    # Beyond the top breakpoint the index is capped at its maximum.
    return 500


def aqi_color(aqi):
    """The AQI category color for an AQI value."""
    for category_max, color in AQI_CATEGORY_COLORS:
        if aqi <= category_max:
            return color
    return AQI_CATEGORY_COLORS[-1][1]


class AirQuality(Overlay):
    """Air quality widget driven by a PurpleAir sensor.

    Draws a compact pill holding a severity dot colored by AQI category and the
    sensor's 10-minute reading. When the reading can't be fetched — no API key,
    a failed request, a sensor that has stopped reporting — the image passes
    through untouched rather than publishing a stale or blank number.
    """

    def __init__(
        self,
        sensor_index,
        place=None,
        size=None,
        subname=None,
        metric="aqi",
        api_key_env="PURPLE_KEY",
        margin=(24, 24),
        font_path="fonts/SourceSansVariable-Bold.ttf",
        font_size=34,
        label="AQI",
        label_font_size=19,
        bg_color=(0, 0, 0, 140),
        text_color=(255, 255, 255),
        dot_radius=12,
        dot_outline_color=(255, 255, 255, 90),
        padding=(16, 12),
        gap=11,
        corner_radius=12,
        cache_seconds=300,
        max_reading_age=3600,
        timeout=10,
    ):
        super().__init__(place or (0, 0), size or (0, 0), subname)
        self.place_auto = place is None
        self.sensor_index = sensor_index
        self.metric = metric
        self.api_key_env = api_key_env
        self.margin = tuple(margin)
        self.font_path = font_path
        self.font_size = font_size
        self.label = label
        self.label_font_size = label_font_size
        self.bg_color = tuple(bg_color)
        self.text_color = tuple(text_color)
        self.dot_radius = dot_radius
        self.dot_outline_color = tuple(dot_outline_color) if dot_outline_color else None
        self.padding = tuple(padding)
        self.gap = gap
        self.corner_radius = corner_radius
        self.cache_seconds = cache_seconds
        self.max_reading_age = max_reading_age
        self.timeout = timeout

    @property
    def _cache_path(self):
        return os.path.join(
            tempfile.gettempdir(), f"gnpc-purpleair-{self.sensor_index}.json"
        )

    def _read_cache(self):
        """The cached reading if it is still fresh, otherwise None."""
        if self.cache_seconds <= 0:
            return None
        try:
            with open(self._cache_path, "r") as f:
                cached = json.load(f)
        except (OSError, ValueError):
            return None

        if time.time() - cached.get("fetched_at", 0) > self.cache_seconds:
            return None
        return cached.get("pm25")

    def _write_cache(self, pm25):
        if self.cache_seconds <= 0:
            return
        payload = {"pm25": pm25, "fetched_at": time.time()}
        # Written via a uniquely named temp file so overlapping cron runs can't
        # read a half-written cache or clobber each other's rename.
        temp_path = f"{self._cache_path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w") as f:
                json.dump(payload, f)
            os.replace(temp_path, self._cache_path)
        except OSError as e:
            logger.warning(f"Could not cache PurpleAir reading: {e}")
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def fetch_pm25(self):
        """The sensor's 10-minute average PM2.5, or None if it is unavailable."""
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            logger.warning(
                f"{self.api_key_env} is not set; skipping air quality overlay"
            )
            return None

        with _purple_air_cache_lock:
            cached = self._read_cache()
            if cached is not None:
                logger.debug(f"Using cached PurpleAir reading: {cached}")
                return cached

            try:
                response = requests.get(
                    PURPLE_AIR_SENSOR_URL.format(sensor_index=self.sensor_index),
                    headers={"X-API-Key": api_key},
                    params={"fields": "pm2.5_10minute,last_seen"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                sensor = response.json().get("sensor", {})
            except (requests.RequestException, ValueError) as e:
                logger.warning(f"Error fetching PurpleAir sensor data: {e}")
                return None

            # The 10-minute average lives under "stats"; older API versions
            # promoted it to the sensor itself.
            pm25 = sensor.get("stats", {}).get("pm2.5_10minute")
            if pm25 is None:
                pm25 = sensor.get("pm2.5_10minute")
            if pm25 is None:
                logger.warning(
                    f"PurpleAir sensor {self.sensor_index} returned no 10-minute value"
                )
                return None

            last_seen = sensor.get("last_seen")
            if (
                self.max_reading_age
                and last_seen
                and time.time() - last_seen > self.max_reading_age
            ):
                logger.warning(
                    f"PurpleAir sensor {self.sensor_index} last reported "
                    f"{(time.time() - last_seen) / 60:.0f} minutes ago; "
                    "skipping air quality overlay"
                )
                return None

            self._write_cache(pm25)
            return pm25

    def _render_widget(self, value_text, color):
        """Draw the widget on a transparent canvas sized to its contents.

        Rendered at 4x and downscaled so the dot and rounded corners come out
        smooth — PIL's drawing primitives are not anti-aliased.
        """
        scale = 4
        pad_x, pad_y = (self.padding[0] * scale, self.padding[1] * scale)
        radius = self.dot_radius * scale
        gap = self.gap * scale

        font = ImageFont.truetype(resolve_path(self.font_path), self.font_size * scale)
        label_font = (
            ImageFont.truetype(
                resolve_path(self.font_path), self.label_font_size * scale
            )
            if self.label
            else None
        )

        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        value_width = measure.textlength(value_text, font=font)
        label_width = (
            measure.textlength(self.label, font=label_font) + gap if self.label else 0
        )

        content_height = max(2 * radius, self.font_size * scale)
        width = int(pad_x * 2 + 2 * radius + gap + value_width + label_width)
        height = int(content_height + pad_y * 2)

        widget = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(widget)
        draw.rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=self.corner_radius * scale,
            fill=self.bg_color,
        )

        middle = height / 2
        dot_center_x = pad_x + radius
        draw.ellipse(
            (
                dot_center_x - radius,
                middle - radius,
                dot_center_x + radius,
                middle + radius,
            ),
            fill=color,
            outline=self.dot_outline_color,
            width=max(1, scale // 2),
        )

        # Nudged up a hair: "lm" centers on the font's full line box, which sits
        # low against the dot because of descender space the digits never use.
        text_x = dot_center_x + radius + gap
        draw.text(
            (text_x, middle - scale),
            value_text,
            font=font,
            fill=self.text_color,
            anchor="lm",
        )
        if self.label:
            draw.text(
                (text_x + value_width + gap, middle - scale),
                self.label,
                font=label_font,
                fill=self.text_color,
                anchor="lm",
            )

        return widget.resize((width // scale, height // scale), Image.LANCZOS)

    def add_overlay(self, image, mod_time_str=""):
        """Add the air quality widget to the image."""
        self.overlayed = io.BytesIO()

        webcam = Image.open(image)
        webcam_with_aq = webcam.copy()

        pm25 = self.fetch_pm25()
        if pm25 is None:
            webcam_with_aq.save(self.overlayed, format="JPEG")
            self.overlayed.seek(0)
            return

        aqi = pm25_to_aqi(pm25)
        value_text = str(aqi) if self.metric == "aqi" else f"{pm25:.1f}"
        widget = self._render_widget(value_text, aqi_color(aqi))
        self.size = widget.size

        if self.place_auto:
            # Top-right corner, inset by the margin.
            self.place = (
                webcam.size[0] - widget.size[0] - self.margin[0],
                self.margin[1],
            )

        webcam_with_aq.paste(widget, self.place, widget)
        webcam_with_aq.save(self.overlayed, format="JPEG")
        self.overlayed.seek(0)


class CompositeOverlay(Overlay):
    """
    Composite overlay that applies multiple overlays sequentially
    to create a single output image.
    """

    def __init__(self, overlays, subname=None):
        # Use the first overlay's subname if no composite subname provided
        if subname is None and overlays:
            subname = getattr(overlays[0], "subname", None)

        super().__init__(place=(0, 0), size=(0, 0), subname=subname)
        self.overlays = overlays

    def add_overlay(self, image, mod_time_str=""):
        """Apply all overlays sequentially to create a composite image."""
        self.overlayed = io.BytesIO()

        # Start with the original image
        current_image = image

        # Apply each overlay in sequence
        for i, overlay in enumerate(self.overlays):
            # For the first overlay, use the original image buffer
            if i == 0:
                overlay.add_overlay(current_image, mod_time_str)
            else:
                # For subsequent overlays, use the previous overlay's output as input
                previous_overlay = self.overlays[i - 1]
                previous_overlay.overlayed.seek(0)  # Reset to beginning
                overlay.add_overlay(previous_overlay.overlayed, mod_time_str)

            # The current processed image is now in this overlay's buffer
            current_image = overlay.overlayed

        # Copy the final result to our own buffer
        if self.overlays:
            final_overlay = self.overlays[-1]
            final_overlay.overlayed.seek(0)
            self.overlayed.write(final_overlay.overlayed.read())
            self.overlayed.seek(0)
