"""
Overlay classes for webcam image processing.
"""

import io
import os
from abc import ABC, abstractmethod
import random
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
    def __init__(self, place, size, img='overlays/logo-shaded.png', subname=None, cover_date=False):
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
            corner_rectangle = Image.open('overlays/corner-rectangle.png')
            webcam_and_logo.paste(corner_rectangle, None)

            # Add datetime
            draw = ImageDraw.Draw(webcam_and_logo)
            font = ImageFont.truetype("fonts/OpenSans-Bold.ttf", 16)
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
    
    def __init__(self, place=None, size=(175, 44), endpoint="https://glacier.org/scripts/post_temp.cgi", subname=None, font_path="fonts/SourceSansVariable-Bold.ttf", 
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

            endpoint_cachebust = f'{self.endpoint}?rand={random.randint(1000, 9999)}'
            response = requests.get(endpoint_cachebust, headers=headers, timeout=10)
            response.raise_for_status()
            # Endpoint returns plaintext response
            temperature_raw = response.text.strip()
            if temperature_raw and temperature_raw != "N/A":
                return f"{temperature_raw} °F"
            else:
                return ""
        except requests.RequestException as e:
            print(f"Error fetching temperature: {e}")
            return ""

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
        background = Image.new('RGBA', actual_bg_size, tuple(self.bg_color))

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

class CompositeOverlay(Overlay):
    """Composite overlay that applies multiple overlays sequentially to create a single output image."""
    
    def __init__(self, overlays, subname=None):
        # Use the first overlay's subname if no composite subname provided
        if subname is None and overlays:
            subname = getattr(overlays[0], 'subname', None)
        
        super().__init__(place=(0, 0), size=(0, 0), subname=subname)
        self.overlays = overlays
    
    def add_overlay(self, image, mod_time_str=''):
        """Apply all overlays sequentially to create a composite image."""
        # Start with the original image
        current_image = image
        
        # Apply each overlay in sequence
        for i, overlay in enumerate(self.overlays):
            # For the first overlay, use the original image buffer
            if i == 0:
                overlay.add_overlay(current_image, mod_time_str)
            else:
                # For subsequent overlays, use the previous overlay's output as input
                previous_overlay = self.overlays[i-1]
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

