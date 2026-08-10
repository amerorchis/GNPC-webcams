"""Unit tests for YAML config loading and object construction."""

import pytest

from config import (
    AirQualityConfig,
    LogoConfig,
    create_webcam_from_config,
    load_config,
    parse_overlay,
)
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

    # lpp uses flat placements
    assert all(isinstance(p, LogoConfig) for p in by_name["lpp"].logo_placements)

    # smv uses grouped placements (list of lists)
    assert all(isinstance(p, list) for p in by_name["smv"].logo_placements)


def test_create_webcam_from_config():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    webcam = create_webcam_from_config(by_name["lpp"])
    assert isinstance(webcam, Webcam)
    assert webcam.file_name_on_server == "lpp.jpg"
    assert all(isinstance(o, Logo) for o in webcam.overlays)


def test_single_item_groups_unwrap_to_plain_overlays():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    # smv's groups each contain one logo, so they should not become composites
    webcam = create_webcam_from_config(by_name["smv"])
    assert all(not isinstance(o, CompositeOverlay) for o in webcam.overlays)


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


def test_unknown_overlay_type_is_rejected():
    with pytest.raises(ValueError):
        parse_overlay({"type": "sparkles", "place": [0, 0], "size": [1, 1]})


def test_mg_air_quality_only_on_the_non_nps_feed():
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


def test_mg_builds_a_composite_for_the_gnpc_feed_only():
    config = load_config("webcams.yaml")
    by_name = {w.name: w for w in config.webcams}

    webcam = create_webcam_from_config(by_name["mg"])
    by_file = {o.get_overlayed_img("mg")[1]: o for o in webcam.overlays}

    assert isinstance(by_file["mg_nps.jpg"], Logo)
    composite = by_file["mg.jpg"]
    assert isinstance(composite, CompositeOverlay)
    assert [type(o) for o in composite.overlays] == [Logo, AirQuality]
