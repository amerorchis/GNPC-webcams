"""Unit tests for YAML config loading and object construction."""

import pytest

from config import (
    AirQualityConfig,
    LogoConfig,
    WebcamConfig,
    create_overlay_from_config,
    create_webcam_from_config,
    load_config,
    parse_overlay,
)
from HttpWebcam import HttpWebcam
from Overlays import AirQuality, CompositeOverlay, Logo
from Webcam import Webcam


def test_load_config_parses_webcams_and_videos():
    config = load_config("webcams.yaml")
    assert len(config.webcams) > 0
    assert len(config.allsky_videos) > 0

    names = [w.name for w in config.webcams]
    assert "dark_sky" in names
    assert "lpp" in names


def test_unused_section_is_not_loaded():
    config = load_config("webcams.yaml")
    names = [w.name for w in config.webcams]
    assert "depot" not in names
    assert "stuck" not in names


def test_blackout_flag_parsed():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}
    assert by_name["smv"].blackout is True
    assert by_name["lpp"].blackout is False


def test_single_and_grouped_placements_parsed():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    # dark_sky uses flat placements
    assert all(isinstance(p, LogoConfig) for p in by_name["dark_sky"].logo_placements)

    # lpp uses grouped placements (list of lists)
    assert all(isinstance(p, list) for p in by_name["lpp"].logo_placements)


def test_create_webcam_from_config():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    webcam = create_webcam_from_config(by_name["lpp"])
    assert isinstance(webcam, Webcam)
    assert webcam.file_name_on_server == "lpp.jpg"
    assert all(isinstance(o, (Logo, CompositeOverlay)) for o in webcam.overlays)


def test_single_item_groups_unwrap_to_plain_overlays():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    # lpp's NPS group holds one logo, so it stays a plain overlay; its GNPC
    # group pairs a logo with the conditions badge and becomes a composite.
    nps, gnpc = create_webcam_from_config(by_name["lpp"]).overlays
    assert isinstance(nps, Logo) and not isinstance(nps, CompositeOverlay)
    assert isinstance(gnpc, CompositeOverlay)


def test_air_quality_config_defaults_match_the_overlay():
    """The factory splats the dataclass, so a stale default here wins silently."""
    import dataclasses
    import inspect

    params = inspect.signature(AirQuality).parameters
    overlay_defaults = {
        name: param.default
        for name, param in params.items()
        if param.default is not inspect.Parameter.empty
    }

    def same(a, b):
        # YAML gives lists where the overlay defaults to tuples
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return tuple(a) == tuple(b)
        return a == b

    mismatched = {}
    for field in dataclasses.fields(AirQualityConfig):
        if field.name not in params:
            mismatched[field.name] = (field.default, "not an AirQuality argument")
        elif field.default is not dataclasses.MISSING and not same(
            field.default, overlay_defaults.get(field.name)
        ):
            mismatched[field.name] = (field.default, overlay_defaults[field.name])

    assert not mismatched, f"config/overlay defaults drifted: {mismatched}"


def test_air_quality_config_covers_every_overlay_option():
    """A new AirQuality argument is unreachable from YAML until it is added here."""
    import dataclasses
    import inspect

    config_fields = {f.name for f in dataclasses.fields(AirQualityConfig)}
    overlay_args = {
        name for name in inspect.signature(AirQuality).parameters if name != "self"
    }
    assert overlay_args - config_fields == set()


@pytest.mark.parametrize(
    "name, url, sensor_index",
    [
        # sensor_index is the PurpleAir unit nearest that camera
        ("tm", "https://www.nps.gov/webcams-glac/TwoMedicine.jpg", 192041),
        ("stmary", "https://www.nps.gov/webcams-glac/StMaryPTZ.jpg", 83937),
    ],
)
def test_nps_cameras_are_fetched_over_http(name, url, sensor_index):
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    camera = by_name[name]
    assert camera.url == url
    assert camera.file_name_on_server is None

    webcam = create_webcam_from_config(camera)
    assert isinstance(webcam, HttpWebcam)
    assert webcam.url == url

    # One published feed: the GNPC logo plus the conditions badge
    assert len(webcam.overlays) == 1
    composite = webcam.overlays[0]
    assert isinstance(composite, CompositeOverlay)
    assert [type(o) for o in composite.overlays] == [Logo, AirQuality]
    assert composite.get_overlayed_img(name)[1] == f"{name}.jpg"
    assert composite.overlays[1].sensor_index == sensor_index


def test_ftp_cameras_are_not_http_cameras():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    assert not isinstance(create_webcam_from_config(by_name["mg"]), HttpWebcam)


@pytest.mark.parametrize(
    "source",
    [
        {},  # neither
        {"file_name_on_server": "tm.jpg", "url": "https://example.org/tm.jpg"},  # both
    ],
)
def test_a_webcam_needs_exactly_one_source(source):
    with pytest.raises(ValueError):
        WebcamConfig(name="tm", logo_placements=[], **source)


def test_unknown_overlay_type_is_rejected():
    with pytest.raises(ValueError):
        parse_overlay({"type": "sparkles", "place": [0, 0], "size": [1, 1]})


def test_st_mary_badge_does_not_buy_the_dead_temperature_field():
    """Sensor 83937 reports no temperature, so the field is not paid for."""
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    badges = [
        o
        for group in by_name["stmary"].logo_placements
        for o in group
        if isinstance(o, AirQualityConfig)
    ]
    assert len(badges) == 1
    assert badges[0].sensor_index == 83937
    assert badges[0].show_temperature is False

    overlay = create_overlay_from_config(badges[0])
    assert "temperature" not in overlay._billed_fields()


def test_air_quality_only_on_the_non_nps_feed():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    groups = by_name["mg"].logo_placements
    nps_group = [g for g in groups if any(o.subname == "nps" for o in g)]
    gnpc_group = [g for g in groups if not any(o.subname == "nps" for o in g)]
    assert len(nps_group) == 1 and len(gnpc_group) == 1

    assert not any(isinstance(o, AirQualityConfig) for o in nps_group[0])
    air_quality = [o for o in gnpc_group[0] if isinstance(o, AirQualityConfig)]
    assert len(air_quality) == 1
    # PurpleAir "Many Glacier Ranger Station"
    assert air_quality[0].sensor_index == 111457


def test_a_composite_is_built_for_the_gnpc_feed_only():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    webcam = create_webcam_from_config(by_name["mg"])
    by_file = {o.get_overlayed_img("mg")[1]: o for o in webcam.overlays}

    assert isinstance(by_file["mg_nps.jpg"], Logo)
    composite = by_file["mg.jpg"]
    assert isinstance(composite, CompositeOverlay)
    assert [type(o) for o in composite.overlays] == [Logo, AirQuality]


def test_the_allsky_feed_carries_no_badge():
    """The DSO cam publishes logo and timestamp only, on both feeds."""
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    placements = by_name["dark_sky"].logo_placements
    assert all(isinstance(p, LogoConfig) for p in placements)

    webcam = create_webcam_from_config(by_name["dark_sky"])
    assert all(isinstance(o, Logo) for o in webcam.overlays)
    assert {o.get_overlayed_img("dark_sky")[1] for o in webcam.overlays} == {
        "dark_sky_nps.jpg",
        "dark_sky.jpg",
    }


def test_nps_logos_stay_inside_the_nps_index_crop():
    """nps.gov crops at least 189px off each side of the 16:9 feeds.

    The logo has to start at or before that so its shading reaches the visible
    edge; a larger x leaves a gap on wide layouts.
    """
    config = load_config("webcams.yaml")

    wide_nps_logos = [
        o
        for w in config.webcams
        for p in w.logo_placements
        for o in (p if isinstance(p, list) else [p])
        # dark_sky's NPS feed is offset vertically instead, and barely cropped
        if isinstance(o, LogoConfig)
        and o.subname == "nps"
        and tuple(o.size) != (299, 68)
    ]
    assert wide_nps_logos
    for logo in wide_nps_logos:
        assert logo.place[0] <= 189, f"logo at x={logo.place[0]} leaves a gap"
