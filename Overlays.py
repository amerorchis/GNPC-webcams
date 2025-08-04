"""
Overlay classes for webcam image processing.
"""

import io
import os
from abc import ABC, abstractmethod
import requests

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv('environment.env')

class Overlay(ABC):
    """Abstract base class for image overlays."""
    
    def __init__(self, place, size, subname=None):
        self.place = place
        self.size = size
        self.subname = subname
        self.overlayed = io.BytesIO()
    
    @abstractmethod
    def add_overlay(self, image, mod_time_str=''):
        """Apply the overlay to the image. Must be implemented by subclasses."""
        pass
    
    def get_overlayed_img(self, name):
        """Get the overlayed image with appropriate filename."""
        name += f'_{self.subname}.jpg' if self.subname else '.jpg'
        return self.overlayed, name

class Logo(Overlay):
    def __init__(self, place, size, img='logo-shaded.png', subname=None, cover_date=False):
        super().__init__(place, size, subname)
        self.logo_img = img
        self.cover_date = cover_date

    def add_overlay(self, image, mod_time_str=''):
        # Open the images
        logo = Image.open(self.logo_img)
        webcam = Image.open(image)

        # Resize logo
        logo = logo.resize(self.size)

        # Create a copy of image
        webcam_and_logo = webcam.copy()

        # Paste logo onto cam at the specified location
        webcam_and_logo.paste(logo, self.place, logo)

        # Cover old datetime
        if self.cover_date:
            corner_rectangle = Image.open('corner-rectangle.png')
            webcam_and_logo.paste(corner_rectangle, None)

            # Add datetime
            draw = ImageDraw.Draw(webcam_and_logo)
            font = ImageFont.truetype("OpenSans-Bold.ttf", 16)
            text_position = (4, 3)
            text_color = (255, 255, 255)
            draw.text(text_position, mod_time_str, font=font, fill=text_color)

        # Save logoed file
        webcam_and_logo.save(self.overlayed, format="JPEG")
        self.overlayed.seek(0)

    def add_logo(self, image, mod_time_str=''):
        """Backward compatibility method."""
        return self.add_overlay(image, mod_time_str)
    
    def get_logoed_img(self, name):
        """Backward compatibility method."""
        return self.get_overlayed_img(name)

class Temperature(Overlay):
    """Temperature overlay that fetches temperature data from an endpoint."""
    
    def __init__(self, place=None, size=(175, 44), endpoint="https://glacier.org/scripts/post_temp.cgi", subname=None, font_path="SourceSansVariable-Bold.ttf", 
                 font_size=38, bg_color=(0, 0, 0, 64), bg_size=(175, 44), text_color=(255, 255, 255)):
        # If place is not provided, it will be calculated in add_overlay based on image dimensions
        super().__init__(place or (0, 0), size, subname)  # Use (0,0) temporarily if place is None
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
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            }

            response = requests.get(self.endpoint, headers=headers, timeout=10)
            response.raise_for_status()
            # Endpoint returns plaintext response
            temperature_raw = response.text.strip()
            if temperature_raw and temperature_raw != "N/A":
                return f"{temperature_raw} °F"
            else:
                return "N/A"
        except requests.RequestException as e:
            print(f"Error fetching temperature: {e}")
            return "N/A"
    
    def _load_bold_font(self):
        """Load font directly from the specified font path."""
        try:
            return ImageFont.truetype(self.font_path, self.font_size)
        except (OSError, IOError):
            # Fallback to default font if file not found
            return ImageFont.load_default()
    
    def add_overlay(self, image, mod_time_str=''):
        """Add temperature overlay to the image."""
        # Open the webcam image
        webcam = Image.open(image)
        
        # Create a copy of the image
        webcam_with_temp = webcam.copy()
        
        # Calculate position if auto-positioning is enabled
        if self.place_auto:
            img_width, img_height = webcam.size
            # Position so top-right corner of overlay is at top-right corner of image
            self.place = (img_width - self.bg_size[0], 0)
        
        # Fetch temperature data
        temperature_text = self.fetch_temperature()
        
        # Load font with bold weight if possible
        try:
            font = self._load_bold_font()
        except (OSError, IOError):
            font = ImageFont.load_default()
        
        # Use fixed background size
        actual_bg_size = self.bg_size

        # Create background rectangle
        background = Image.new('RGBA', actual_bg_size, self.bg_color)

        # Create text overlay
        text_overlay = Image.new('RGBA', actual_bg_size, (0, 0, 0, 0))
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

class LogoWithTemperature(Overlay):
    """Composite overlay that combines logo and temperature."""
    
    def __init__(self, place, size, img='logo-shaded.png', subname=None, cover_date=False, 
                 temp_endpoint="https://glacier.org/scripts/post_temp.cgi", temp_font_path="SourceSansVariable-Bold.ttf", 
                 temp_font_size=38, temp_bg_color=(0, 0, 0, 64), temp_bg_size=(175, 44), temp_text_color=(255, 255, 255), temp_place=False):
        super().__init__(place, size, subname)
        # Logo properties
        self.logo_img = img
        self.cover_date = cover_date
        # Temperature properties
        self.temp_endpoint = temp_endpoint
        self.temp_font_path = temp_font_path
        self.temp_font_size = temp_font_size
        self.temp_bg_color = temp_bg_color
        self.temp_bg_size = temp_bg_size
        self.temp_text_color = temp_text_color
        self.temp_place = temp_place

    def _fetch_temperature(self):
        """Fetch temperature from the endpoint."""
        try:
            # Headers to mimic a browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            }

            response = requests.get(self.temp_endpoint, headers=headers, timeout=10)
            response.raise_for_status()
            # Endpoint returns plaintext response
            temperature_raw = response.text.strip()
            if temperature_raw and temperature_raw != "N/A":
                return f"{temperature_raw} °F"
            else:
                return "N/A"
        except requests.RequestException as e:
            print(f"Error fetching temperature: {e}")
            return "N/A"
    
    def _load_temp_bold_font(self):
        """Load font directly from the specified font path."""
        try:
            return ImageFont.truetype(self.temp_font_path, self.temp_font_size)
        except (OSError, IOError):
            # Fallback to default font if file not found
            return ImageFont.load_default()
    
    def _calculate_temp_place(self, img_width, img_height):
        """Calculate the position for the temperature overlay."""
        if self.temp_place is False:
            # Default to top-right corner
            return (img_width - self.temp_bg_size[0], 0)
        elif isinstance(self.temp_place, tuple):
            return self.temp_place
        else:
            raise ValueError("temp_place must be a tuple or False")

    def add_overlay(self, image, mod_time_str=''):
        """Apply both logo and temperature overlays to the image."""
        # Open the images
        logo = Image.open(self.logo_img)
        webcam = Image.open(image)

        # Resize logo
        logo = logo.resize(self.size)

        # Create a copy of image
        webcam_with_overlays = webcam.copy()

        # Paste logo onto cam at the specified location
        webcam_with_overlays.paste(logo, self.place, logo)

        # Cover old datetime if requested
        if self.cover_date:
            corner_rectangle = Image.open('corner-rectangle.png')
            webcam_with_overlays.paste(corner_rectangle, None)

            # Add datetime
            draw = ImageDraw.Draw(webcam_with_overlays)
            font = ImageFont.truetype("OpenSans-Bold.ttf", 16)
            text_position = (4, 3)
            text_color = (255, 255, 255)
            draw.text(text_position, mod_time_str, font=font, fill=text_color)

        # Add temperature overlay at designated place
        img_width, img_height = webcam_with_overlays.size
        temp_place = self._calculate_temp_place(img_width, img_height)

        # Fetch temperature data
        temperature_text = self._fetch_temperature()

        # Load font
        try:
            temp_font = self._load_temp_bold_font()
        except (OSError, IOError):
            temp_font = ImageFont.load_default()

        # Create temperature background
        temp_background = Image.new('RGBA', self.temp_bg_size, self.temp_bg_color)

        # Create temperature text overlay
        temp_text_overlay = Image.new('RGBA', self.temp_bg_size, (0, 0, 0, 0))
        temp_draw = ImageDraw.Draw(temp_text_overlay)
        
        # Calculate text dimensions to center it
        text_bbox = temp_draw.textbbox((0, 0), temperature_text, font=temp_font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        # Center text horizontally, shift up vertically
        text_x = (self.temp_bg_size[0] - text_width) // 2
        text_y = (self.temp_bg_size[1] - text_height) // 2 - 10
        
        # Draw temperature text
        temp_draw.text((text_x, text_y), temperature_text, font=temp_font, fill=self.temp_text_color)

        # Composite temperature background and text
        temp_final = Image.alpha_composite(temp_background, temp_text_overlay)

        # Paste temperature overlay onto the image
        webcam_with_overlays.paste(temp_final, temp_place, temp_final)

        # Save final file with both overlays
        webcam_with_overlays.save(self.overlayed, format="JPEG")
        self.overlayed.seek(0)
    
    def add_logo(self, image, mod_time_str=''):
        """Backward compatibility method."""
        return self.add_overlay(image, mod_time_str)
    
    def get_logoed_img(self, name):
        """Backward compatibility method."""
        return self.get_overlayed_img(name)