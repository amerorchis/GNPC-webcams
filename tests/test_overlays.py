"""Unit tests for overlay composition using in-memory images (no network/FTP)."""

import io
import os
import time

import pytest
import requests
from PIL import Image

import Overlays
from Overlays import (
    AirQuality,
    CompositeOverlay,
    Logo,
    Temperature,
    aqi_color,
    pm25_to_aqi,
)
from paths import resolve_path


def make_image_buffer(size=(1200, 1100), color=(10, 60, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer


def test_logo_overlay_produces_image_of_same_size():
    logo = Logo(place=(0, 944), size=(612, 137))
    logo.add_overlay(make_image_buffer(), "9:15 am Jul. 02, 2026")

    result = Image.open(logo.overlayed)
    assert result.size == (1200, 1100)


@pytest.mark.skipif(
    not os.path.exists(resolve_path("fonts/OpenSans-Bold.ttf")),
    reason="fonts are not tracked in git; skip on checkouts without them",
)
def test_logo_overlay_with_cover_date():
    logo = Logo(
        place=(0, 944),
        size=(612, 137),
        cover_date=True,
        cover_date_bg_color=(0, 0, 0, 255),
        cover_date_size=(300, 30),
    )
    logo.add_overlay(make_image_buffer(), "9:15 am Jul. 02, 2026")

    result = Image.open(logo.overlayed)
    assert result.size == (1200, 1100)


def test_repeated_add_overlay_does_not_grow_buffer():
    logo = Logo(place=(0, 944), size=(612, 137))

    source = make_image_buffer()
    logo.add_overlay(source, "")
    first = logo.overlayed.getvalue()
    logo.overlayed.read()  # Simulate an upload consuming the buffer

    source.seek(0)
    logo.add_overlay(source, "")
    second = logo.overlayed.getvalue()

    assert len(first) == len(second)


def test_composite_overlay_applies_all_and_does_not_grow_buffer():
    composite = CompositeOverlay(
        [
            Logo(place=(0, 944), size=(612, 137), subname="nps"),
            Logo(place=(140, 944), size=(612, 137)),
        ]
    )

    source = make_image_buffer()
    composite.add_overlay(source, "")
    first = composite.overlayed.getvalue()
    assert Image.open(io.BytesIO(first)).size == (1200, 1100)

    composite.overlayed.read()
    source.seek(0)
    composite.add_overlay(source, "")
    assert len(composite.overlayed.getvalue()) == len(first)


def test_composite_overlay_uses_first_subname():
    composite = CompositeOverlay(
        [
            Logo(place=(0, 944), size=(612, 137), subname="nps"),
            Logo(place=(140, 944), size=(612, 137)),
        ]
    )
    _, file_name = composite.get_overlayed_img("smv")
    assert file_name == "smv_nps.jpg"


def test_get_overlayed_img_naming():
    assert Logo(place=(0, 0), size=(1, 1)).get_overlayed_img("mg")[1] == "mg.jpg"
    assert (
        Logo(place=(0, 0), size=(1, 1), subname="nps").get_overlayed_img("mg")[1]
        == "mg_nps.jpg"
    )


def test_temperature_overlay_with_mocked_fetch(monkeypatch):
    temperature = Temperature()
    monkeypatch.setattr(temperature, "fetch_temperature", lambda: "72 °F")

    temperature.add_overlay(make_image_buffer(), "")
    result = Image.open(temperature.overlayed)
    assert result.size == (1200, 1100)

    # Auto-positioning puts the box at the top-right corner
    assert temperature.place == (1200 - temperature.bg_size[0], 0)


def test_temperature_overlay_without_data_passes_image_through(monkeypatch):
    temperature = Temperature()
    monkeypatch.setattr(temperature, "fetch_temperature", lambda: "")

    temperature.add_overlay(make_image_buffer(), "")
    result = Image.open(temperature.overlayed)
    assert result.size == (1200, 1100)


needs_fonts = pytest.mark.skipif(
    not os.path.exists(resolve_path("fonts/SourceSansVariable-Bold.ttf")),
    reason="fonts are not tracked in git; skip on checkouts without them",
)


@pytest.mark.parametrize(
    "pm25,aqi",
    [
        (0.0, 0),
        (9.0, 50),
        (9.1, 51),
        (35.4, 100),
        (35.5, 101),
        (55.4, 150),
        (55.5, 151),
        (125.4, 200),
        (125.5, 201),
        (225.4, 300),
        (225.5, 301),
        (325.4, 500),
        (1000.0, 500),  # Off the top of the scale, capped rather than extrapolated
    ],
)
def test_pm25_to_aqi_matches_epa_breakpoints(pm25, aqi):
    assert pm25_to_aqi(pm25) == aqi


def test_pm25_to_aqi_truncates_to_one_decimal():
    # The EPA formula truncates rather than rounds, so 9.09 stays in "Good"
    assert pm25_to_aqi(9.09) == pm25_to_aqi(9.0)


def test_aqi_color_categories():
    assert aqi_color(0) == (0, 228, 0)
    assert aqi_color(75) == (255, 255, 0)
    assert aqi_color(150) == (255, 126, 0)
    assert aqi_color(200) == (255, 0, 0)
    assert aqi_color(300) == (143, 63, 151)
    assert aqi_color(999) == (126, 0, 35)


@needs_fonts
def test_air_quality_overlay_auto_positions_top_right(monkeypatch):
    air_quality = AirQuality(sensor_index=1)
    monkeypatch.setattr(air_quality, "fetch_pm25", lambda: 12.0)

    air_quality.add_overlay(make_image_buffer(), "")
    result = Image.open(air_quality.overlayed)
    assert result.size == (1200, 1100)

    widget_width, _ = air_quality.size
    assert air_quality.place == (1200 - widget_width - 24, 24)


@needs_fonts
def test_air_quality_widget_widens_for_longer_readings(monkeypatch):
    def widget_width(pm25):
        overlay = AirQuality(sensor_index=1)
        monkeypatch.setattr(overlay, "fetch_pm25", lambda: pm25)
        overlay.add_overlay(make_image_buffer(), "")
        return overlay.size[0]

    assert widget_width(300.0) > widget_width(2.0)


@needs_fonts
def test_air_quality_overlay_can_show_raw_pm25(monkeypatch):
    air_quality = AirQuality(sensor_index=1, metric="pm25", label="PM2.5")
    monkeypatch.setattr(air_quality, "fetch_pm25", lambda: 12.34)

    rendered = []
    monkeypatch.setattr(
        air_quality,
        "_render_widget",
        lambda text, color: rendered.append((text, color)) or Image.new("RGBA", (1, 1)),
    )
    air_quality.add_overlay(make_image_buffer(), "")

    assert rendered == [("12.3", aqi_color(pm25_to_aqi(12.34)))]


def test_air_quality_overlay_without_data_passes_image_through(monkeypatch):
    air_quality = AirQuality(sensor_index=1)
    monkeypatch.setattr(air_quality, "fetch_pm25", lambda: None)

    air_quality.add_overlay(make_image_buffer(), "")
    result = Image.open(air_quality.overlayed)
    assert result.size == (1200, 1100)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def sensor_payload(pm25=20.0, last_seen=None):
    return {
        "sensor": {
            "last_seen": last_seen if last_seen is not None else int(time.time()),
            "stats": {"pm2.5_10minute": pm25},
        }
    }


@pytest.fixture
def purple_air(monkeypatch, tmp_path):
    """An AirQuality overlay with an API key and a cache isolated to tmp_path."""
    monkeypatch.setenv("PURPLE_KEY", "test-key")
    monkeypatch.setattr(Overlays.tempfile, "gettempdir", lambda: str(tmp_path))
    return AirQuality(sensor_index=1)


def test_fetch_pm25_reads_the_ten_minute_average(monkeypatch, purple_air):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(sensor_payload(pm25=42.5))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)

    assert purple_air.fetch_pm25() == 42.5
    assert calls[0][0].endswith("/sensors/1")
    assert calls[0][1]["headers"]["X-API-Key"] == "test-key"
    assert "pm2.5_10minute" in calls[0][1]["params"]["fields"]


def test_fetch_pm25_caches_between_calls(monkeypatch, purple_air):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(sensor_payload(pm25=42.5))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)

    assert purple_air.fetch_pm25() == 42.5
    # A second overlay (another camera, or the next cron run) reuses the file
    assert AirQuality(sensor_index=1).fetch_pm25() == 42.5
    assert len(calls) == 1


def test_fetch_pm25_refetches_once_the_cache_expires(monkeypatch, purple_air):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(sensor_payload(pm25=42.5))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)
    purple_air.cache_seconds = 0

    purple_air.fetch_pm25()
    purple_air.fetch_pm25()
    assert len(calls) == 2


def test_fetch_pm25_ignores_a_sensor_that_stopped_reporting(monkeypatch, purple_air):
    stale = int(time.time()) - 2 * 3600
    monkeypatch.setattr(
        Overlays.requests,
        "get",
        lambda url, **kw: FakeResponse(sensor_payload(last_seen=stale)),
    )

    assert purple_air.fetch_pm25() is None


def test_fetch_pm25_survives_a_failed_request(monkeypatch, purple_air):
    def fake_get(url, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(Overlays.requests, "get", fake_get)

    assert purple_air.fetch_pm25() is None


def test_fetch_pm25_without_an_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("PURPLE_KEY", raising=False)
    monkeypatch.setattr(Overlays.tempfile, "gettempdir", lambda: str(tmp_path))

    assert AirQuality(sensor_index=1).fetch_pm25() is None
