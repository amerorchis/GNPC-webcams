"""
Custom class to represent an individual logo placement and webcam.
"""

import io
import os
from time import sleep
from ftplib import FTP, error_perm
from datetime import datetime, timedelta
from typing import List

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv('environment.env')

class Logo:
    def __init__(self, place, size, img = 'logo-shaded.png', subname = None, cover_date = False):
        self.place = place
        self.size = size
        self.logo_img = img
        self.subname = subname
        self.cover_date = cover_date
        self.logoed = io.BytesIO()

    def add_logo(self, image, mod_time_str = ''):
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
        webcam_and_logo.save(self.logoed, format="JPEG")
        self.logoed.seek(0)

    def get_logoed_img(self, name):
        name += f'_{self.subname}.jpg' if self.subname else '.jpg'
        return self.logoed, name

class Webcam:
    def __init__(self, name, file_name_on_server, logo_placements: List[Logo], username=None, password=None):
        self.name = name
        self.file_buffer = io.BytesIO()

        self.file_name_on_server = file_name_on_server
        self.logo_placements = logo_placements
        self.username = username
        self.password = password

        self.mod_time = None
        self.mod_time_str = ''
        self.upload = []

    def get(self):
        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(self.username, self.password)

        def get_image():
            ftp.retrbinary(f'RETR {self.file_name_on_server}', self.file_buffer.write)
            self.file_buffer.seek(0)

            self.set_mod_time(ftp) # Set the file modification time.

            # Close the FTP connection
            ftp.quit()

        # Try to save the image.
        try:
            get_image()
        # If it's not there, wait 6 seconds and try again
        except error_perm as e:
            if str(e).startswith('550'):
                sleep(6)
            try:
                get_image()

            # If it's still not there, raise an exception.
            except error_perm as exc:
                raise FileNotFoundError(f"{self.name} wasn't found in the folder.") from exc

    def add_logo(self):
        for i in self.logo_placements:
            i.add_logo(self.file_buffer, self.mod_time_str)

    def upload_image(self):
        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(os.getenv('username'), os.getenv('password'))

        for i in self.logo_placements:
            # Get file and name for each logo placement.
            logoed, file_name = i.get_logoed_img(self.name)

            # Store the file
            ftp.storbinary('STOR ' + file_name, logoed)
            self.upload += [f'https://glacier.org/webcam/{file_name}']

        ftp.quit() # Close connection

    def set_mod_time(self, ftp: FTP):
        # Send the MDTM command to the FTP server
        try:
            response = ftp.sendcmd(f"MDTM {self.file_name_on_server}")

            # The response will be in the format: '213 YYYYMMDDHHMMSS'
            if response.startswith('213'):
                time_str = response[4:].strip()
                mod_time = datetime.strptime(time_str, '%Y%m%d%H%M%S') - timedelta(hours=6)
                self.mod_time = mod_time
                self.mod_time_str = mod_time.strftime('%-I:%M%p %b. %d, %Y')

        # 550 errors can be ignored
        except error_perm as e:
            if str(e).startswith('550'):
                pass
