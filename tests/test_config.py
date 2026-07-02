"""Unit tests for YAML config loading and object construction."""

from config import (
    LogoConfig,
    create_webcam_from_config,
    load_config,
)
from Overlays import CompositeOverlay, Logo
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
