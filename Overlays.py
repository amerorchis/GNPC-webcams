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

# glacier.org rejects both a spoofed browser User-Agent and the requests
# default with a 403, so identify the script honestly.
USER_AGENT = "GNPC-webcams/1.0 (+https://glacier.org/webcam)"


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
            headers = {
                # The endpoint 403s a spoofed browser User-Agent (and the
                # requests default), so identify the script for what it is.
                "User-Agent": USER_AGENT,
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

# Official AQI categories: (top of the category, color, badge wording). The
# wording is shortened from the EPA's own names to fit a webcam corner —
# "Unhealthy for Sensitive Groups" would nearly double the badge width.
AQI_CATEGORIES = (
    (50, (0, 228, 0), "Good"),
    (100, (255, 255, 0), "Moderate"),
    (150, (255, 126, 0), "Sensitive Groups"),
    (200, (255, 0, 0), "Unhealthy"),
    (300, (143, 63, 151), "Very Unhealthy"),
    (500, (126, 0, 35), "Hazardous"),
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


def aqi_category(aqi):
    """The (color, wording) of the AQI category an AQI value falls in."""
    for category_max, color, name in AQI_CATEGORIES:
        if aqi <= category_max:
            return color, name
    return AQI_CATEGORIES[-1][1], AQI_CATEGORIES[-1][2]


def aqi_color(aqi):
    """The AQI category color for an AQI value."""
    return aqi_category(aqi)[0]


def epa_correct_pm25(pa_cf1, humidity):
    """Apply the EPA's extended US-wide correction to a PurpleAir reading.

    Barkjohn et al. (2021), extended in 2022 for wildfire-scale concentrations;
    this is the correction AirNow applies to PurpleAir data on its Fire and
    Smoke Map. It takes the CF=1 channel and a relative humidity, and returns an
    estimate of what a reference monitor would report.
    """
    pa = max(pa_cf1, 0.0)
    rh = 50.0 if humidity is None else humidity

    if pa < 30:
        return 0.524 * pa - 0.0862 * rh + 5.75
    if pa < 50:
        # Blend between the low and mid slopes so the curve stays continuous.
        blend = pa / 20 - 3 / 2
        return (0.786 * blend + 0.524 * (1 - blend)) * pa - 0.0862 * rh + 5.75
    if pa < 210:
        return 0.786 * pa - 0.0862 * rh + 5.75
    if pa < 260:
        # Blend again into the high-concentration curve.
        blend = pa / 50 - 21 / 5
        return (
            (0.69 * blend + 0.786 * (1 - blend)) * pa
            - 0.0862 * rh * (1 - blend)
            + 2.966 * blend
            + 5.75 * (1 - blend)
            + 8.84e-4 * pa**2 * blend
        )
    return 2.966 + 0.69 * pa + 8.84e-4 * pa**2


# Below this the two PM2.5 channels report the same number, so there is no
# ratio to measure — and the ATM value available for free is rounded to a whole
# number, which at single digits is too coarse to divide by.
CF1_RATIO_FLOOR = 10.0


def _cf1_ratio(pm25_atm, pm25_cf1):
    """How much higher the CF=1 channel reads than the ATM channel right now.

    The two are identical in clean air and settle at roughly 3:2 in smoke.
    Clamped because a single noisy pair of instantaneous samples must not be
    able to scale the 10-minute average into nonsense.
    """
    if not pm25_atm or not pm25_cf1 or pm25_atm < CF1_RATIO_FLOOR:
        return 1.0
    return min(max(pm25_cf1 / pm25_atm, 1.0), 1.6)


def _tracked_text_width(draw, text, font, tracking):
    """Width of text drawn with extra spacing between every glyph."""
    if not text:
        return 0
    glyphs = sum(draw.textlength(character, font=font) for character in text)
    return glyphs + tracking * (len(text) - 1)


def _draw_tracked_text(draw, xy, text, font, fill, tracking):
    """Draw text one glyph at a time, spaced out.

    Small uppercase text set solid is hard to read at webcam scale; letting it
    breathe costs nothing and PIL has no tracking of its own.
    """
    x, y = xy
    for character in text:
        draw.text((x, y), character, font=font, fill=fill, anchor="ls")
        x += draw.textlength(character, font=font) + tracking


class AirQuality(Overlay):
    """Air quality widget driven by a PurpleAir sensor.

    Draws a compact pill: a severity dot colored by AQI category sitting beside
    the sensor's 10-minute reading, with the category wording centered on its
    own line beneath. When the reading can't be fetched — no API key, a failed
    request, a sensor that has stopped reporting — the image passes through
    untouched rather than publishing a stale or blank number.
    """

    def __init__(
        self,
        sensor_index,
        place=None,
        size=None,
        subname=None,
        metric="aqi",
        conversion="epa",
        api_key_env="PURPLE_KEY",
        anchor="bottom-right",
        margin=(20, 20),
        show_temperature=True,
        temperature_source="purpleair",
        temperature_offset=-8.0,
        temperature_endpoint="https://glacier.org/scripts/post_temp.cgi",
        temperature_label="°F",
        font_path="fonts/SourceSansVariable-Bold.ttf",
        font_size=44,
        label="AQI",
        label_font_size=21,
        show_category=True,
        # The category is the first thing to go when the frame is scaled down to
        # a phone, so it is set larger and tracked tighter than the label above
        # it, and the plate is opaque enough to hold its own against a sunlit
        # roof or snowfield behind it.
        category_font_size=20,
        category_tracking=1.2,
        line_gap=3,
        divider_color=(255, 255, 255, 85),
        bg_color=(0, 0, 0, 175),
        text_color=(255, 255, 255),
        dot_radius=15,
        dot_outline_color=(255, 255, 255, 90),
        padding=(16, 12),
        gap=11,
        corner_radius=12,
        # Every measurement above is in pixels of a 1920x1080 frame. On a
        # smaller frame the badge would take up proportionally more of the
        # picture, so cameras with a different frame size set this to the ratio
        # of their width to 1920 and the whole badge, margin included, comes out
        # the same fraction of the image.
        scale=1.0,
        cache_seconds=600,
        max_reading_age=3600,
        timeout=10,
    ):
        super().__init__(place or (0, 0), size or (0, 0), subname)
        self.place_auto = place is None
        self.sensor_index = sensor_index
        self.metric = metric
        self.conversion = conversion
        self.api_key_env = api_key_env
        self.anchor = anchor
        self.margin = tuple(margin)
        self.show_temperature = show_temperature
        self.temperature_source = temperature_source
        self.temperature_offset = temperature_offset
        self.temperature_endpoint = temperature_endpoint
        self.temperature_label = temperature_label
        self.divider_color = tuple(divider_color) if divider_color else None
        self.font_path = font_path
        self.font_size = font_size
        self.label = label
        self.label_font_size = label_font_size
        self.show_category = show_category
        self.category_font_size = category_font_size
        self.category_tracking = category_tracking
        self.line_gap = line_gap
        self.bg_color = tuple(bg_color)
        self.text_color = tuple(text_color)
        self.dot_radius = dot_radius
        self.dot_outline_color = tuple(dot_outline_color) if dot_outline_color else None
        self.padding = tuple(padding)
        self.gap = gap
        self.corner_radius = corner_radius
        self.scale = scale
        self.cache_seconds = cache_seconds
        self.max_reading_age = max_reading_age
        self.timeout = timeout

    def _billed_fields(self):
        """The PurpleAir fields worth paying for, given how this badge is set up.

        `humidity_a` rather than `humidity`: channel A's reading costs 1 point
        where the A/B average costs 2, and these sensors carry a humidity module
        on channel A only, so the two are the same number. Should a two-module
        sensor ever be used, the channels would have to disagree by ~12 %RH to
        move the corrected PM2.5 by a single microgram.
        """
        fields = ["pm2.5_10minute", "pm2.5_cf_1", "humidity_a"]
        if self.show_temperature and self.temperature_source == "purpleair":
            fields.append("temperature")
        return fields

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
        return cached.get("reading")

    def _write_cache(self, reading):
        if self.cache_seconds <= 0:
            return
        payload = {"reading": reading, "fetched_at": time.time()}
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

    def fetch_reading(self):
        """The sensor's latest numbers, or None if they are unavailable.

        Returns the 10-minute PM2.5 average, the humidity, and the ratio between
        the sensor's two PM2.5 channels — see `pm25` for why that ratio matters.
        """
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
                    # Billed per field, so ask only for what can't be derived:
                    # the "stats" block arrives with the 10-minute average and
                    # carries the current ATM reading and its timestamp for
                    # free, making pm2.5_atm and last_seen redundant purchases.
                    params={"fields": ",".join(self._billed_fields())},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                sensor = response.json().get("sensor", {})
            except (requests.RequestException, ValueError) as e:
                logger.warning(f"Error fetching PurpleAir sensor data: {e}")
                return None

            # The 10-minute average lives under "stats"; older API versions
            # promoted it to the sensor itself.
            stats = sensor.get("stats", {})
            pm25 = stats.get("pm2.5_10minute")
            if pm25 is None:
                pm25 = sensor.get("pm2.5_10minute")
            if pm25 is None:
                logger.warning(
                    f"PurpleAir sensor {self.sensor_index} returned no 10-minute value"
                )
                return None

            # stats.time_stamp is when the sensor last reported, matching the
            # last_seen field exactly but without being billed for it.
            last_seen = stats.get("time_stamp") or sensor.get("last_seen")
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

            reading = {
                "pm25": pm25,
                "humidity": sensor.get("humidity_a"),
                "temperature": sensor.get("temperature"),
                # stats.pm2.5 is the current ATM reading rounded to a whole
                # number — free with the 10-minute average, and precise enough
                # for a ratio that gets clamped anyway.
                "cf1_ratio": _cf1_ratio(stats.get("pm2.5"), sensor.get("pm2.5_cf_1")),
            }
            self._write_cache(reading)
            return reading

    def pm25(self):
        """The PM2.5 concentration to publish, or None if it is unavailable.

        With the default EPA conversion this is not the sensor's raw number: the
        correction is defined against the CF=1 channel, but the API only offers
        10-minute averages of the ATM channel. The two channels track each other
        by a fixed ratio at any given concentration, so the current
        CF=1-to-ATM ratio converts the 10-minute average before correcting it.
        """
        reading = self.fetch_reading()
        if reading is None:
            return None

        pm25 = reading["pm25"]
        if self.conversion == "epa":
            pm25 = epa_correct_pm25(
                pm25 * reading.get("cf1_ratio", 1.0), reading.get("humidity")
            )
        return pm25

    def temperature(self):
        """Ambient temperature in °F, or None if it is unavailable.

        The PurpleAir thermometer sits inside the sensor's enclosure, where the
        electronics and sunlight both warm it, so its reading runs hot. The
        offset applied here is PurpleAir's own published figure (-4.4 °C), which
        keeps the badge agreeing with what purpleair.com shows for the sensor —
        worth more than a private calibration nobody else can reproduce.
        """
        if not self.show_temperature:
            return None

        if self.temperature_source == "purpleair":
            reading = self.fetch_reading()
            if reading is None or reading.get("temperature") is None:
                return None
            return reading["temperature"] + self.temperature_offset

        return self._fetch_endpoint_temperature()

    def _fetch_endpoint_temperature(self):
        """Temperature from a plaintext HTTP endpoint, or None."""
        try:
            response = requests.get(
                self.temperature_endpoint,
                headers={"User-Agent": USER_AGENT},
                params={"rand": random.randint(1000, 9999)},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return float(response.text.strip())
        except (requests.RequestException, ValueError) as e:
            logger.warning(f"Error fetching temperature: {e}")
            return None

    def _font(self, size, scale):
        return ImageFont.truetype(resolve_path(self.font_path), int(size * scale))

    def _render_reading(self, value_text, unit_text, scale):
        """The number and its unit label, cropped to their own ink.

        Cropping to the ink rather than to the font's line box is what lets the
        caller center this against the dot: font metrics reserve space for
        ascenders and descenders that digits never use.
        """
        font = self._font(self.font_size, scale)
        label_font = self._font(self.label_font_size, scale)
        gap = self.gap * scale

        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        value_width = measure.textlength(value_text, font=font)
        label_width = (
            gap + measure.textlength(unit_text, font=label_font) if unit_text else 0
        )

        ascent, descent = font.getmetrics()
        canvas = Image.new(
            "RGBA",
            (math.ceil(value_width + label_width) + scale, ascent + descent),
            (0, 0, 0, 0),
        )
        draw = ImageDraw.Draw(canvas)
        draw.text((0, ascent), value_text, font=font, fill=self.text_color, anchor="ls")
        if unit_text:
            # Sharing a baseline rather than a center line: the small label is
            # meant to read as a unit with the number, not float beside it.
            draw.text(
                (value_width + gap, ascent),
                unit_text,
                font=label_font,
                fill=self.text_color,
                anchor="ls",
            )
        return canvas.crop(canvas.getbbox())

    def _render_content(self, value_text, color, category_text, scale, unit_text=None):
        """Lay out the dot and reading on one line, the category beneath.

        Keeping the dot inline with the number ties the color to the value it
        describes and lets the category wording use the badge's full width
        instead of being indented past the dot.
        """
        category_font = self._font(self.category_font_size, scale)
        radius = self.dot_radius * scale if color else 0
        gap = self.gap * scale
        tracking = self.category_tracking * scale

        reading = self._render_reading(
            value_text, self.label if unit_text is None else unit_text, scale
        )
        top_width = 2 * radius + gap + reading.width
        top_height = max(2 * radius, reading.height)

        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        category_width = (
            _tracked_text_width(measure, category_text, category_font, tracking)
            if category_text
            else 0
        )
        category_ascent, category_descent = category_font.getmetrics()

        width = math.ceil(max(top_width, category_width))
        height = math.ceil(
            top_height
            + (
                self.line_gap * scale + category_ascent + category_descent
                if category_text
                else 0
            )
        )

        content = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(content)

        # Each line is centered on the other: the reading is wider for a short
        # category like "Good", the category wider for "Sensitive Groups".
        top_x = (width - top_width) / 2
        middle = top_height / 2
        if color:
            draw.ellipse(
                (top_x, middle - radius, top_x + 2 * radius, middle + radius),
                fill=color,
                outline=self.dot_outline_color,
                width=max(1, scale // 2),
            )
        content.paste(
            reading,
            (int(top_x + 2 * radius + gap), int(middle - reading.height / 2)),
            reading,
        )
        if category_text:
            _draw_tracked_text(
                draw,
                ((width - category_width) / 2, height - category_descent),
                category_text,
                category_font,
                self.text_color,
                tracking,
            )

        return content.crop(content.getbbox())

    def _render_square(self, value_text, color, category_text, temperature_text, scale):
        """The two-measurement badge: temperature above, AQI below, on a square.

        The temperature is centered on its own rather than sharing the AQI's
        number column: it comes from a different instrument and means something
        unrelated, so the hairline separates two peers instead of a heading from
        its body.
        """
        num_font = self._font(self.font_size, scale)
        unit_font = self._font(self.label_font_size, scale)
        category_font = self._font(self.category_font_size, scale)
        gap = int(self.gap * scale * 0.7)
        radius = self.dot_radius * scale
        tracking = self.category_tracking * scale

        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        temp_width = measure.textlength(temperature_text, font=num_font)
        value_width = measure.textlength(value_text, font=num_font)
        unit_width = max(
            measure.textlength(self.temperature_label, font=unit_font),
            measure.textlength(self.label, font=unit_font),
        )
        category_width = (
            _tracked_text_width(measure, category_text, category_font, tracking)
            if category_text
            else 0
        )

        # The AQI row sets the layout: [dot][right-aligned number][unit]
        number_right = 2 * radius + gap + max(temp_width, value_width)
        row_width = number_right + gap + unit_width
        content_width = int(max(row_width, category_width))

        num_ascent, num_descent = num_font.getmetrics()
        cat_ascent, cat_descent = category_font.getmetrics()
        row_height = num_ascent + num_descent
        category_height = cat_ascent + cat_descent if category_text else 0
        side = int(
            max(
                content_width + 2 * self.padding[0] * scale,
                2 * row_height + category_height + 4 * self.padding[1] * scale,
            )
        )

        tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)
        draw.rounded_rectangle(
            (0, 0, side - 1, side - 1),
            radius=int(self.corner_radius * scale * 1.7),
            fill=self.bg_color,
        )

        # Spread the rows down the square instead of clumping them in the middle
        step = (side - (2 * row_height + category_height)) / 4
        left = (side - content_width) / 2 + (content_width - row_width) / 2

        y = step
        group_width = (
            temp_width
            + gap
            + measure.textlength(self.temperature_label, font=unit_font)
        )
        temp_x = (side - group_width) / 2
        draw.text(
            (temp_x, y + num_ascent),
            temperature_text,
            font=num_font,
            fill=self.text_color,
            anchor="ls",
        )
        draw.text(
            (temp_x + temp_width + gap, y + num_ascent),
            self.temperature_label,
            font=unit_font,
            fill=self.text_color,
            anchor="ls",
        )
        y += row_height + step

        if self.divider_color:
            rule_width = content_width * 0.92
            rule_x = (side - rule_width) / 2
            rule_y = y - step / 2
            draw.rectangle(
                (rule_x, rule_y, rule_x + rule_width, rule_y + max(2, scale // 2)),
                fill=self.divider_color,
            )

        dot_middle = y + num_ascent - num_ascent * 0.33
        draw.ellipse(
            (left, dot_middle - radius, left + 2 * radius, dot_middle + radius),
            fill=color,
            outline=self.dot_outline_color,
            width=max(1, scale // 2),
        )
        draw.text(
            (left + number_right, y + num_ascent),
            value_text,
            font=num_font,
            fill=self.text_color,
            anchor="rs",
        )
        draw.text(
            (left + number_right + gap, y + num_ascent),
            self.label,
            font=unit_font,
            fill=self.text_color,
            anchor="ls",
        )
        y += row_height + step

        if category_text:
            _draw_tracked_text(
                draw,
                ((side - category_width) / 2, y + cat_ascent),
                category_text,
                category_font,
                self.text_color,
                tracking,
            )

        return tile.resize(self._final_size(side, side, scale), Image.LANCZOS)

    def _final_size(self, width, height, supersample):
        """Size to come down to from the supersampled canvas.

        Folds `scale` into the same LANCZOS step that removes the supersampling,
        so a scaled-down badge is resampled once rather than twice.
        """
        divisor = supersample / self.scale
        return (max(1, int(width // divisor)), max(1, int(height // divisor)))

    def _render_widget(
        self, value_text, color, category_text=None, temperature_text=None
    ):
        """Draw the badge on a transparent canvas sized to its contents.

        Rendered at 4x and downscaled so the dot and rounded corners come out
        smooth — PIL's drawing primitives are not anti-aliased.
        """
        scale = 4
        pad_x, pad_y = (self.padding[0] * scale, self.padding[1] * scale)

        if value_text is not None and temperature_text is not None:
            return self._render_square(
                value_text, color, category_text, temperature_text, scale
            )

        # Only one measurement survived, so collapse to the single-value pill
        # rather than publishing a square with an empty half.
        if value_text is not None:
            content = self._render_content(value_text, color, category_text, scale)
        else:
            content = self._render_content(
                temperature_text, None, None, scale, unit_text=self.temperature_label
            )
        width = content.width + 2 * pad_x
        height = content.height + 2 * pad_y

        widget = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(widget).rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=self.corner_radius * scale,
            fill=self.bg_color,
        )
        widget.paste(content, (pad_x, pad_y), content)

        return widget.resize(self._final_size(width, height, scale), Image.LANCZOS)

    def _anchored_place(self, image_size, widget_size):
        """Where to paste the badge, given the configured corner."""
        vertical, _, horizontal = self.anchor.partition("-")
        margin_x = int(round(self.margin[0] * self.scale))
        margin_y = int(round(self.margin[1] * self.scale))
        x = (
            margin_x
            if horizontal == "left"
            else image_size[0] - widget_size[0] - margin_x
        )
        y = margin_y if vertical == "top" else image_size[1] - widget_size[1] - margin_y
        return (x, y)

    def add_overlay(self, image, mod_time_str=""):
        """Add the air quality badge to the image."""
        self.overlayed = io.BytesIO()

        webcam = Image.open(image)
        webcam_with_aq = webcam.copy()

        pm25 = self.pm25()
        temperature = self.temperature()

        value_text = None
        color = None
        category = None
        if pm25 is not None:
            aqi = pm25_to_aqi(pm25)
            color, category_name = aqi_category(aqi)
            category = category_name.upper() if self.show_category else None
            value_text = str(aqi) if self.metric == "aqi" else f"{pm25:.1f}"

        temperature_text = None if temperature is None else f"{round(temperature)}"

        if value_text is None and temperature_text is None:
            # Nothing trustworthy to show; publish the frame untouched.
            webcam_with_aq.save(self.overlayed, format="JPEG")
            self.overlayed.seek(0)
            return

        widget = self._render_widget(value_text, color, category, temperature_text)
        self.size = widget.size

        if self.place_auto:
            self.place = self._anchored_place(webcam.size, widget.size)

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
