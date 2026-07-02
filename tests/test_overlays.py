"""Unit tests for overlay composition using in-memory images (no network/FTP)."""

import io
import os

import pytest
from PIL import Image

from Overlays import CompositeOverlay, Logo, Temperature
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
