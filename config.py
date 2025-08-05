"""
Configuration dataclasses and YAML loading for GNPC webcams.
"""

import os
import yaml
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Union, Tuple

from Webcam import Webcam
from AllskyVideo import AllskyVideo    
from Overlays import Logo, Temperature

logger = logging.getLogger(__name__)

@dataclass
class LogoConfig:
    """Configuration for a Logo overlay."""
    place: Tuple[int, int]
    size: Tuple[int, int]
    img: str = 'overlays/logo-shaded.png'
    subname: Optional[str] = None
    cover_date: bool = False

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
class WebcamConfig:
    """Configuration for a webcam."""
    name: str
    file_name_on_server: str
    logo_placements: List[Union[LogoConfig, TemperatureConfig, List[Union[LogoConfig, TemperatureConfig]]]]
    
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

def load_config(config_file: str = 'webcams.yaml') -> AppConfig:
    """Load configuration from YAML file."""
    logger.info(f"Loading configuration from {config_file}")
    
    try:
        with open(config_file, 'r') as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file {config_file} not found")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        raise
    
    # Parse webcams
    webcams = []
    for webcam_data in data.get('webcams', []):
        # Parse logo_placements
        logo_placements = []
        for placement in webcam_data.get('logo_placements', []):
            if isinstance(placement, list):
                # Group of overlays
                group = []
                for overlay in placement:
                    if overlay['type'] == 'logo':
                        group.append(LogoConfig(**{k: v for k, v in overlay.items() if k != 'type'}))
                    elif overlay['type'] == 'temperature':
                        group.append(TemperatureConfig(**{k: v for k, v in overlay.items() if k != 'type'}))
                logo_placements.append(group)
            else:
                # Single overlay
                if placement['type'] == 'logo':
                    logo_placements.append(LogoConfig(**{k: v for k, v in placement.items() if k != 'type'}))
                elif placement['type'] == 'temperature':
                    logo_placements.append(TemperatureConfig(**{k: v for k, v in placement.items() if k != 'type'}))
        
        webcam = WebcamConfig(
            name=webcam_data['name'],
            file_name_on_server=webcam_data['file_name_on_server'],
            logo_placements=logo_placements
        )
        webcams.append(webcam)
    
    # Parse allsky videos
    allsky_videos = []
    for video_data in data.get('allsky_videos', []):
        video = AllskyVideoConfig(**video_data)
        allsky_videos.append(video)
    
    config = AppConfig(webcams=webcams, allsky_videos=allsky_videos)
    logger.info(f"Loaded configuration: {len(config.webcams)} webcams, {len(config.allsky_videos)} allsky videos")
    
    return config

def create_overlay_from_config(overlay_config: Union[LogoConfig, TemperatureConfig]):
    """Create an overlay object from configuration."""
    
    if isinstance(overlay_config, LogoConfig):
        return Logo(
            place=overlay_config.place,
            size=overlay_config.size,
            img=overlay_config.img,
            subname=overlay_config.subname,
            cover_date=overlay_config.cover_date
        )
    elif isinstance(overlay_config, TemperatureConfig):
        return Temperature(
            place=overlay_config.place,
            size=overlay_config.size,
            endpoint=overlay_config.endpoint,
            subname=overlay_config.subname,
            font_path=overlay_config.font_path,
            font_size=overlay_config.font_size,
            bg_color=overlay_config.bg_color,
            bg_size=overlay_config.bg_size,
            text_color=overlay_config.text_color
        )
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
    
    return Webcam(
        name=webcam_config.name,
        file_name_on_server=webcam_config.file_name_on_server,
        logo_placements=logo_placements
    )

def create_allsky_video_from_config(video_config: AllskyVideoConfig):
    """Create an AllskyVideo object from configuration."""
    
    return AllskyVideo(
        name=video_config.name,
        file_name_on_server=video_config.file_name_on_server,
        logo_place=video_config.logo_place,
        logo_size=video_config.logo_size,
        username=os.getenv('ftp_get_user'),
        password=os.getenv('ftp_get_pwd')
    )