"""Unit tests for overlay composition using in-memory images (no network/FTP)."""

import io
import json
import time

import pytest
import requests
from PIL import Image, ImageChops

import Overlays
from Overlays import (
    AirQuality,
    CompositeOverlay,
    Logo,
    _cf1_ratio,
    aqi_category,
    aqi_color,
    epa_correct_pm25,
    pm25_to_aqi,
)


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


class RecordingOverlay(Overlays.Overlay):
    """Notes what it was handed and draws nothing."""

    def __init__(self):
        super().__init__(place=(0, 0), size=(0, 0))
        self.inputs = []

    def apply(self, image, mod_time_str=""):
        self.inputs.append(image)
        return image


def test_composite_overlay_chains_decoded_images_and_encodes_once():
    """The overlays in a group hand each other pixels, not JPEG bytes.

    A re-encode between every overlay would compound the loss on every GNPC
    feed, which all carry a logo and a badge.
    """
    first, second = RecordingOverlay(), RecordingOverlay()
    composite = CompositeOverlay([first, second])

    composite.add_overlay(make_image_buffer(), "")

    assert all(isinstance(i, Image.Image) for i in first.inputs + second.inputs)
    assert second.inputs[0] is first.inputs[0]  # Same canvas, no round-trip
    assert first.overlayed.getvalue() == b""  # Only the composite encodes
    assert Image.open(composite.overlayed).size == (1200, 1100)


def test_overlays_encode_above_pillows_default_quality():
    """Quality 75 softens a frame the camera has already compressed once."""
    noisy = Image.effect_noise((400, 300), 64).convert("RGB")
    source = io.BytesIO()
    noisy.save(source, format="JPEG", quality=95)
    source.seek(0)

    baseline = io.BytesIO()
    noisy.save(baseline, format="JPEG", quality=75)

    logo = Logo(place=(0, 0), size=(1, 1))
    logo.add_overlay(source, "")

    assert Overlays.JPEG_QUALITY >= 90
    assert len(logo.overlayed.getvalue()) > 1.3 * len(baseline.getvalue())


def test_air_quality_fetches_the_sensor_once_per_frame(monkeypatch):
    """Temperature and AQI come out of the same reading; buy it once."""
    air_quality = AirQuality(sensor_index=1)
    calls = []

    def fetch_reading():
        calls.append(1)
        return {"pm25": 10.0, "humidity": 40, "temperature": 71, "cf1_ratio": 1.0}

    monkeypatch.setattr(air_quality, "fetch_reading", fetch_reading)
    air_quality.add_overlay(make_image_buffer(), "")

    assert len(calls) == 1
    assert air_quality.size != (0, 0)  # The badge was drawn with both values


def test_get_overlayed_img_naming():
    assert Logo(place=(0, 0), size=(1, 1)).get_overlayed_img("mg")[1] == "mg.jpg"
    assert (
        Logo(place=(0, 0), size=(1, 1), subname="nps").get_overlayed_img("mg")[1]
        == "mg_nps.jpg"
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


def test_aqi_category_wording():
    assert aqi_category(11)[1] == "Good"
    assert aqi_category(124)[1] == "Sensitive Groups"
    assert aqi_category(263)[1] == "Very Unhealthy"
    assert aqi_category(999)[1] == "Hazardous"


@pytest.mark.parametrize("boundary", [30, 50, 210, 260])
def test_epa_correction_is_continuous_across_its_bands(boundary):
    # The blending bands exist to avoid a jump in the published number
    below = epa_correct_pm25(boundary - 1e-6, 50)
    above = epa_correct_pm25(boundary, 50)
    assert abs(above - below) < 0.01


def test_epa_correction_lowers_clean_air_and_raises_smoke():
    # PurpleAir's CF=1 channel under-reads at low concentrations relative to a
    # reference monitor and over-reads in smoke; the correction goes both ways
    assert epa_correct_pm25(10, 50) < 10
    assert epa_correct_pm25(200, 50) > 200 * 0.7


def test_epa_correction_defaults_humidity_when_the_sensor_omits_it():
    assert epa_correct_pm25(100, None) == epa_correct_pm25(100, 50)


def test_epa_correction_never_goes_negative_on_a_clean_sensor():
    assert epa_correct_pm25(0, 90) == pytest.approx(0.524 * 0 - 0.0862 * 90 + 5.75)


def test_cf1_ratio_clamped_to_a_plausible_range():
    assert _cf1_ratio(100.0, 150.0) == pytest.approx(1.5)
    assert _cf1_ratio(100.0, 90.0) == 1.0  # Never below parity
    assert _cf1_ratio(100.0, 500.0) == 1.6  # Never runaway
    assert _cf1_ratio(None, 150.0) == 1.0
    assert _cf1_ratio(0.0, 150.0) == 1.0


def test_cf1_ratio_ignores_single_digit_readings():
    # The free ATM value is rounded to a whole number, so dividing by it at
    # single digits would amplify rounding into the published number
    assert _cf1_ratio(4, 6) == 1.0
    assert _cf1_ratio(9, 14) == 1.0
    assert _cf1_ratio(10, 15) == pytest.approx(1.5)


def stub_readings(monkeypatch, overlay, pm25=12.0, temperature=None):
    """Pin both measurements so no test touches the network."""
    monkeypatch.setattr(overlay, "pm25", lambda reading: pm25)
    monkeypatch.setattr(overlay, "temperature", lambda reading: temperature)
    return overlay


def test_air_quality_overlay_anchors_bottom_right_by_default(monkeypatch):
    air_quality = stub_readings(monkeypatch, AirQuality(sensor_index=1))

    air_quality.add_overlay(make_image_buffer(), "")
    result = Image.open(air_quality.overlayed)
    assert result.size == (1200, 1100)

    width, height = air_quality.size
    assert air_quality.place == (1200 - width - 20, 1100 - height - 20)


@pytest.mark.parametrize(
    "anchor,expected",
    [
        ("top-left", "left-top"),
        ("top-right", "right-top"),
        ("bottom-left", "left-bottom"),
        ("bottom-right", "right-bottom"),
    ],
)
def test_air_quality_overlay_honours_every_anchor(monkeypatch, anchor, expected):
    air_quality = stub_readings(monkeypatch, AirQuality(sensor_index=1, anchor=anchor))
    air_quality.add_overlay(make_image_buffer(), "")

    x, y = air_quality.place
    width, height = air_quality.size
    horizontal = "left" if x == 20 else "right"
    vertical = "top" if y == 20 else "bottom"
    assert f"{horizontal}-{vertical}" == expected
    if horizontal == "right":
        assert x == 1200 - width - 20
    if vertical == "bottom":
        assert y == 1100 - height - 20


def test_air_quality_widget_grows_when_the_category_is_shown(monkeypatch):
    def widget_size(**kwargs):
        overlay = stub_readings(monkeypatch, AirQuality(sensor_index=1, **kwargs))
        overlay.add_overlay(make_image_buffer(), "")
        return overlay.size

    with_category = widget_size(show_category=True)
    without_category = widget_size(show_category=False)
    assert with_category[1] > without_category[1]


def test_air_quality_scale_shrinks_the_badge_and_its_margin(monkeypatch):
    """Cameras with a smaller frame scale the badge to match it."""

    def badge(**kwargs):
        overlay = stub_readings(monkeypatch, AirQuality(sensor_index=1, **kwargs))
        overlay.add_overlay(make_image_buffer(), "")
        return overlay.size, overlay.place

    (full_width, full_height), _ = badge()
    (half_width, half_height), half_place = badge(scale=0.5)

    assert half_width == pytest.approx(full_width / 2, abs=2)
    assert half_height == pytest.approx(full_height / 2, abs=2)
    # The margin scales too, or the badge would sit twice as far off the corner
    # relative to the frame as it does at full size.
    assert half_place == (1200 - half_width - 10, 1100 - half_height - 10)


def capture_render(monkeypatch, overlay):
    """Record the arguments the overlay would draw, without drawing them."""
    rendered = []
    monkeypatch.setattr(
        overlay,
        "_render_widget",
        lambda *args: rendered.append(args) or Image.new("RGBA", (1, 1)),
    )
    overlay.add_overlay(make_image_buffer(), "")
    return rendered


def test_air_quality_overlay_can_show_raw_pm25(monkeypatch):
    air_quality = AirQuality(sensor_index=1, metric="pm25", label="PM2.5")
    stub_readings(monkeypatch, air_quality, pm25=12.34)

    value, color, category, temperature = capture_render(monkeypatch, air_quality)[0]
    assert value == "12.3"
    assert color == aqi_color(pm25_to_aqi(12.34))
    assert temperature is None


def test_air_quality_overlay_labels_the_category_in_caps(monkeypatch):
    air_quality = stub_readings(monkeypatch, AirQuality(sensor_index=1), pm25=45.0)
    assert capture_render(monkeypatch, air_quality)[0][2] == "SENSITIVE GROUPS"


def test_air_quality_overlay_can_omit_the_category(monkeypatch):
    air_quality = stub_readings(
        monkeypatch, AirQuality(sensor_index=1, show_category=False), pm25=45.0
    )
    assert capture_render(monkeypatch, air_quality)[0][2] is None


def test_air_quality_overlay_rounds_the_temperature(monkeypatch):
    air_quality = stub_readings(
        monkeypatch, AirQuality(sensor_index=1), pm25=45.0, temperature=61.6
    )
    assert capture_render(monkeypatch, air_quality)[0][3] == "62"


def test_air_quality_overlay_without_data_passes_image_through(monkeypatch):
    """Neither reading arrived, so the frame must publish completely untouched."""
    air_quality = stub_readings(
        monkeypatch, AirQuality(sensor_index=1), pm25=None, temperature=None
    )

    source = make_image_buffer()
    air_quality.add_overlay(source, "")

    source.seek(0)
    before = Image.open(source).convert("RGB")
    after = Image.open(air_quality.overlayed).convert("RGB")
    assert after.size == (1200, 1100)
    # Not just the same size — the same pixels, with nothing drawn on top
    assert ImageChops.difference(before, after).getbbox() is None
    assert air_quality.size == (0, 0)


def test_air_quality_badge_is_square_when_both_readings_are_present(monkeypatch):
    air_quality = stub_readings(
        monkeypatch, AirQuality(sensor_index=1), pm25=45.0, temperature=61.0
    )
    air_quality.add_overlay(make_image_buffer(), "")
    width, height = air_quality.size
    assert width == height


def test_air_quality_badge_collapses_when_only_one_reading_survives(monkeypatch):
    """A square with an empty half would read as broken."""
    aqi_only = stub_readings(monkeypatch, AirQuality(sensor_index=1), pm25=45.0)
    aqi_only.add_overlay(make_image_buffer(), "")
    assert aqi_only.size[0] > aqi_only.size[1]

    temp_only = stub_readings(
        monkeypatch, AirQuality(sensor_index=1), pm25=None, temperature=61.0
    )
    temp_only.add_overlay(make_image_buffer(), "")
    assert temp_only.size[0] > temp_only.size[1]


def test_air_quality_badge_omits_the_dot_when_only_temperature_survives(monkeypatch):
    """The dot encodes AQI severity, so it must not appear without an AQI."""
    temp_only = stub_readings(
        monkeypatch, AirQuality(sensor_index=1), pm25=None, temperature=61.0
    )
    both = stub_readings(
        monkeypatch, AirQuality(sensor_index=1), pm25=45.0, temperature=61.0
    )
    temp_only.add_overlay(make_image_buffer(), "")
    both.add_overlay(make_image_buffer(), "")
    assert temp_only.size[0] < both.size[0]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def sensor_payload(pm25=20.0, last_seen=None, humidity=50, atm=20, cf1=None):
    """A response shaped like the one the three billed fields actually return."""
    sensor = {
        "humidity_a": humidity,
        "stats": {
            "pm2.5": atm,
            "pm2.5_10minute": pm25,
            "time_stamp": last_seen if last_seen is not None else int(time.time()),
        },
    }
    if cf1 is not None:
        sensor["pm2.5_cf_1"] = cf1
    return {"sensor": sensor}


@pytest.fixture
def purple_air(monkeypatch, tmp_path):
    """An AirQuality overlay with an API key and a cache isolated to tmp_path."""
    monkeypatch.setenv("PURPLE_KEY", "test-key")
    monkeypatch.setattr(Overlays.tempfile, "gettempdir", lambda: str(tmp_path))
    return AirQuality(sensor_index=1)


def test_fetch_reading_reads_the_ten_minute_average(monkeypatch, purple_air):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(sensor_payload(pm25=42.5, humidity=61))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)

    reading = purple_air.fetch_reading()
    assert reading["pm25"] == 42.5
    assert reading["humidity"] == 61
    assert calls[0][0].endswith("/sensors/1")
    assert calls[0][1]["headers"]["X-API-Key"] == "test-key"


def test_only_the_unavoidable_fields_are_billed(monkeypatch, purple_air):
    """Each extra field costs points, and pm2.5_atm/last_seen come free."""
    calls = []
    monkeypatch.setattr(
        Overlays.requests,
        "get",
        lambda url, **kw: calls.append(kw) or FakeResponse(sensor_payload()),
    )

    purple_air.show_temperature = False
    purple_air.fetch_reading()
    requested = calls[0]["params"]["fields"].split(",")
    # humidity_a, not humidity: same reading on these sensors for half the points
    assert sorted(requested) == ["humidity_a", "pm2.5_10minute", "pm2.5_cf_1"]
    assert "humidity" not in requested


def test_temperature_is_only_billed_when_purpleair_supplies_it(purple_air):
    purple_air.show_temperature = False
    assert "temperature" not in purple_air._billed_fields()

    purple_air.show_temperature = True
    purple_air.temperature_source = "endpoint"
    assert "temperature" not in purple_air._billed_fields()

    purple_air.temperature_source = "purpleair"
    assert "temperature" in purple_air._billed_fields()


def test_temperature_applies_the_enclosure_offset(purple_air):
    purple_air.fetch_reading = lambda: {"pm25": 10.0, "temperature": 71}
    assert purple_air.temperature() == 71 + purple_air.temperature_offset


def test_temperature_is_none_when_the_sensor_omits_it(purple_air):
    purple_air.fetch_reading = lambda: {"pm25": 10.0, "temperature": None}
    assert purple_air.temperature() is None


def test_temperature_can_be_switched_off(purple_air):
    purple_air.show_temperature = False
    purple_air.fetch_reading = lambda: {"pm25": 10.0, "temperature": 71}
    assert purple_air.temperature() is None


def test_staleness_comes_from_the_free_stats_timestamp(monkeypatch, purple_air):
    stale = int(time.time()) - 2 * 3600
    payload = sensor_payload(last_seen=stale)
    assert "last_seen" not in payload["sensor"]  # Not requested, so not present
    monkeypatch.setattr(
        Overlays.requests, "get", lambda url, **kw: FakeResponse(payload)
    )

    assert purple_air.fetch_reading() is None


def test_fetch_reading_caches_between_calls(monkeypatch, purple_air):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(sensor_payload(pm25=42.5))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)

    assert purple_air.fetch_reading()["pm25"] == 42.5
    # A second overlay (another camera, or the next cron run) reuses the file
    assert AirQuality(sensor_index=1).fetch_reading()["pm25"] == 42.5
    assert len(calls) == 1


def test_fetch_reading_refetches_once_the_cache_expires(monkeypatch, purple_air):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(sensor_payload(pm25=42.5))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)
    purple_air.cache_seconds = 0

    purple_air.fetch_reading()
    purple_air.fetch_reading()
    assert len(calls) == 2


def test_fetch_reading_ignores_a_sensor_that_stopped_reporting(monkeypatch, purple_air):
    stale = int(time.time()) - 2 * 3600
    monkeypatch.setattr(
        Overlays.requests,
        "get",
        lambda url, **kw: FakeResponse(sensor_payload(last_seen=stale)),
    )

    assert purple_air.fetch_reading() is None


def test_fetch_reading_survives_a_failed_request(monkeypatch, purple_air):
    def fake_get(url, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(Overlays.requests, "get", fake_get)

    assert purple_air.fetch_reading() is None


def test_fetch_reading_falls_back_to_a_backup_sensor(monkeypatch, purple_air):
    stale = int(time.time()) - 2 * 3600
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/sensors/1"):
            return FakeResponse(sensor_payload(last_seen=stale))
        return FakeResponse(sensor_payload(pm25=7.5))

    monkeypatch.setattr(Overlays.requests, "get", fake_get)
    purple_air.fallback_sensors = (2,)

    assert purple_air.fetch_reading()["pm25"] == 7.5
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["1", "2"]


def test_a_working_primary_sensor_never_reaches_the_backup(monkeypatch, purple_air):
    calls = []
    monkeypatch.setattr(
        Overlays.requests,
        "get",
        lambda url, **kw: calls.append(url) or FakeResponse(sensor_payload(pm25=7.5)),
    )
    purple_air.fallback_sensors = (2,)

    purple_air.fetch_reading()
    assert len(calls) == 1


def test_an_offline_sensor_is_not_re_bought_every_run(monkeypatch, purple_air):
    """Eight cameras a minute would otherwise each pay for the same dead sensor."""
    stale = int(time.time()) - 2 * 3600
    calls = []
    monkeypatch.setattr(
        Overlays.requests,
        "get",
        lambda url, **kw: (
            calls.append(url) or FakeResponse(sensor_payload(last_seen=stale))
        ),
    )

    assert purple_air.fetch_reading() is None
    assert AirQuality(sensor_index=1).fetch_reading() is None
    assert len(calls) == 1


def test_a_cached_miss_expires_sooner_than_a_cached_reading(monkeypatch, purple_air):
    stale = int(time.time()) - 2 * 3600
    calls = []
    monkeypatch.setattr(
        Overlays.requests,
        "get",
        lambda url, **kw: (
            calls.append(url) or FakeResponse(sensor_payload(last_seen=stale))
        ),
    )

    purple_air.fetch_reading()

    # Age the cached miss past its own life while leaving it well inside the
    # life a real reading would have had.
    age = purple_air.miss_cache_seconds + 1
    assert age < purple_air.cache_seconds
    cache_path = purple_air._cache_path(1)
    with open(cache_path) as f:
        cached = json.load(f)
    cached["fetched_at"] -= age
    with open(cache_path, "w") as f:
        json.dump(cached, f)

    purple_air.fetch_reading()
    assert len(calls) == 2


def test_fetch_reading_without_an_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("PURPLE_KEY", raising=False)
    monkeypatch.setattr(Overlays.tempfile, "gettempdir", lambda: str(tmp_path))

    assert AirQuality(sensor_index=1).fetch_reading() is None


def test_pm25_applies_the_epa_correction_to_the_scaled_cf1_channel(purple_air):
    # ATM 100 / CF=1 150 means the 10-minute ATM average of 60 corresponds to a
    # CF=1 average of 90, which is what the correction is defined against.
    purple_air.fetch_reading = lambda: {
        "pm25": 60.0,
        "humidity": 40,
        "cf1_ratio": 1.5,
    }

    assert purple_air.pm25() == pytest.approx(epa_correct_pm25(90.0, 40))


def test_pm25_can_publish_the_uncorrected_reading(purple_air):
    purple_air.conversion = "none"
    purple_air.fetch_reading = lambda: {
        "pm25": 60.0,
        "humidity": 40,
        "cf1_ratio": 1.5,
    }

    assert purple_air.pm25() == 60.0


def test_pm25_without_a_reading(purple_air):
    purple_air.fetch_reading = lambda: None
    assert purple_air.pm25() is None
