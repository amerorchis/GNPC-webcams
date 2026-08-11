"""
Configuration dataclasses and YAML loading for GNPC webcams.
"""

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple, Union

import yaml

from AllskyVideo import AllskyVideo
from HttpWebcam import HttpWebcam
from Overlays import AirQuality, Logo, Temperature
from paths import resolve_path
from Webcam import Webcam

logger = logging.getLogger(__name__)


@dataclass
class LogoConfig:
    """Configuration for a Logo overlay."""

    place: Tuple[int, int]
    size: Tuple[int, int]
    img: str = "overlays/logo-shaded.png"
    subname: Optional[str] = None
    cover_date: bool = False
    cover_date_img: str = "overlays/corner-rectangle.png"
    cover_date_bg_color: Optional[Tuple[int, int, int, int]] = None
    cover_date_size: Optional[Tuple[int, int]] = None
    cover_date_position: Tuple[int, int] = (0, 0)
    cover_date_font_path: str = "fonts/OpenSans-Bold.ttf"
    cover_date_font_size: int = 16
    cover_date_text_position: Tuple[int, int] = (4, 3)
    cover_date_text_color: Tuple[int, int, int] = (255, 255, 255)
    cover_date_text_scale: float = 1.0


@dataclass
class TemperatureConfig:
    """Configuration for a Temperature overlay."""

    place: Optional[Tuple[int, int]] = None
    size: Tuple[int, int] = (175, 44)
    endpoint: str = "https://glacier.org/scripts/post_temp.cgi"
    subname: Optional[str] = None
    font_path: str = "fonts/SourceSansVariable-Bold.ttf"
    font_size: int = 38
    bg_color: Tuple[int, int, int, int] = (0, 0, 0, 64)
    bg_size: Tuple[int, int] = (175, 44)
    text_color: Tuple[int, int, int] = (255, 255, 255)


@dataclass
class AirQualityConfig:
    """Configuration for an AirQuality overlay."""

    # Every default here must match AirQuality.__init__ — the factory splats
    # this dataclass, so a stale value here silently overrides the class.
    # test_air_quality_config_defaults_match_the_overlay guards the pairing.
    sensor_index: int
    place: Optional[Tuple[int, int]] = None
    size: Optional[Tuple[int, int]] = None
    subname: Optional[str] = None
    metric: str = "aqi"
    conversion: str = "epa"
    api_key_env: str = "PURPLE_KEY"
    anchor: str = "bottom-right"
    margin: Tuple[int, int] = (20, 20)
    show_temperature: bool = True
    temperature_source: str = "purpleair"
    temperature_offset: float = -8.0
    temperature_endpoint: str = "https://glacier.org/scripts/post_temp.cgi"
    temperature_label: str = "°F"
    font_path: str = "fonts/SourceSansVariable-Bold.ttf"
    font_size: int = 44
    label: str = "AQI"
    label_font_size: int = 21
    show_category: bool = True
    category_font_size: int = 20
    category_tracking: float = 1.2
    line_gap: int = 3
    divider_color: Optional[Tuple[int, int, int, int]] = (255, 255, 255, 85)
    bg_color: Tuple[int, int, int, int] = (0, 0, 0, 175)
    text_color: Tuple[int, int, int] = (255, 255, 255)
    dot_radius: int = 15
    dot_outline_color: Optional[Tuple[int, int, int, int]] = (255, 255, 255, 90)
    padding: Tuple[int, int] = (16, 12)
    gap: int = 11
    corner_radius: int = 12
    # Ratio of this camera's frame width to 1920, so the badge stays the same
    # fraction of the picture on a smaller frame.
    scale: float = 1.0
    cache_seconds: int = 600
    max_reading_age: int = 3600
    timeout: int = 10


OverlayConfig = Union[LogoConfig, TemperatureConfig, AirQualityConfig]


@dataclass
class WebcamConfig:
    """Configuration for a webcam.

    The source is either a file on the glacier.org FTP server
    (`file_name_on_server`) or a URL (`url`) — exactly one of the two.
    """

    name: str
    logo_placements: List[Union[OverlayConfig, List[OverlayConfig]]]
    file_name_on_server: Optional[str] = None
    url: Optional[str] = None
    blackout: bool = False

    def __post_init__(self):
        if bool(self.file_name_on_server) == bool(self.url):
            raise ValueError(
                f"Webcam {self.name!r} needs exactly one source: "
                "file_name_on_server (FTP) or url (HTTP)"
            )


@dataclass
class AllskyVideoConfig:
    """Configuration for an AllskyVideo."""

    name: str
    file_name_on_server: str
    logo_place: Tuple[int, int]
    logo_size: Tuple[int, int]


@dataclass
class AppConfig:
    """Main application configuration."""

    webcams: List[WebcamConfig] = field(default_factory=list)
    allsky_videos: List[AllskyVideoConfig] = field(default_factory=list)


OVERLAY_CONFIG_TYPES = {
    "logo": LogoConfig,
    "temperature": TemperatureConfig,
    "air_quality": AirQualityConfig,
}


def parse_overlay(overlay_data: dict) -> OverlayConfig:
    """Build an overlay config dataclass from one YAML overlay entry."""
    overlay_type = overlay_data.get("type")
    config_class = OVERLAY_CONFIG_TYPES.get(overlay_type)
    if config_class is None:
        raise ValueError(f"Unknown overlay type: {overlay_type!r}")
    return config_class(**{k: v for k, v in overlay_data.items() if k != "type"})


def load_config(config_file: str = "webcams.yaml") -> AppConfig:
    """Load configuration from YAML file (relative paths resolve to the repo dir)."""
    config_file = resolve_path(config_file)
    logger.info(f"Loading configuration from {config_file}")

    try:
        with open(config_file, "r") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file {config_file} not found")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        raise

    # Parse webcams
    webcams = []
    for webcam_data in data.get("webcams", []):
        # Parse logo_placements
        logo_placements = []
        for placement in webcam_data.get("logo_placements", []):
            if isinstance(placement, list):
                # Group of overlays composited into one output image
                logo_placements.append(
                    [parse_overlay(overlay) for overlay in placement]
                )
            else:
                logo_placements.append(parse_overlay(placement))

        webcam = WebcamConfig(
            name=webcam_data["name"],
            file_name_on_server=webcam_data.get("file_name_on_server"),
            url=webcam_data.get("url"),
            logo_placements=logo_placements,
            blackout=webcam_data.get("blackout", False),
        )
        webcams.append(webcam)

    # Parse allsky videos
    allsky_videos = []
    for video_data in data.get("allsky_videos", []):
        video = AllskyVideoConfig(**video_data)
        allsky_videos.append(video)

    config = AppConfig(webcams=webcams, allsky_videos=allsky_videos)
    logger.info(
        "Loaded configuration: %d webcams, %d allsky videos",
        len(config.webcams),
        len(config.allsky_videos),
    )

    return config


def create_overlay_from_config(overlay_config: OverlayConfig):
    """Create an overlay object from configuration."""

    if isinstance(overlay_config, LogoConfig):
        return Logo(**asdict(overlay_config))
    elif isinstance(overlay_config, TemperatureConfig):
        kwargs = asdict(overlay_config)
        kwargs["bg_color"] = tuple(kwargs["bg_color"])
        kwargs["text_color"] = tuple(kwargs["text_color"])
        return Temperature(**kwargs)
    elif isinstance(overlay_config, AirQualityConfig):
        return AirQuality(**asdict(overlay_config))
    else:
        raise ValueError(f"Unknown overlay config type: {type(overlay_config)}")


def create_webcam_from_config(webcam_config: WebcamConfig):
    """Create a Webcam object from configuration."""

    # Convert logo_placements to overlay objects
    logo_placements = []
    for placement in webcam_config.logo_placements:
        if isinstance(placement, list):
            # Group of overlays - convert each one
            group = tuple(create_overlay_from_config(overlay) for overlay in placement)
            logo_placements.append(group)
        else:
            # Single overlay
            logo_placements.append(create_overlay_from_config(placement))

    if webcam_config.url:
        return HttpWebcam(
            name=webcam_config.name,
            url=webcam_config.url,
            logo_placements=logo_placements,
            blackout=webcam_config.blackout,
        )

    return Webcam(
        name=webcam_config.name,
        file_name_on_server=webcam_config.file_name_on_server,
        logo_placements=logo_placements,
        blackout=webcam_config.blackout,
    )


def create_allsky_video_from_config(video_config: AllskyVideoConfig):
    """Create an AllskyVideo object from configuration."""

    return AllskyVideo(
        name=video_config.name,
        file_name_on_server=video_config.file_name_on_server,
        logo_place=video_config.logo_place,
        logo_size=video_config.logo_size,
        username=os.getenv("ftp_get_user"),
        password=os.getenv("ftp_get_pwd"),
    )
