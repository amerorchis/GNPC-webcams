"""
Custom class to represent an individual webcam.
"""

import io
import os
from time import sleep
from ftplib import FTP, error_perm
from datetime import datetime, timedelta

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv('environment.env')

class Webcam:
    def __init__(self, name, file_name_on_server, logo_place, logo_size, username=None, password=None):
        self.name = name
        self.file_buffer = io.BytesIO()
        self.logoed = io.BytesIO()

        self.file_name_on_server = file_name_on_server
        self.logo_place = logo_place
        self.logo_size = logo_size
        self.username = username
        self.password = password

        self.mod_time = None
        self.mod_time_str = ''
        self.upload = None

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
        # Open the images
        logo = Image.open('logo-shaded.png')
        webcam = Image.open(self.file_buffer)

        # Resize logo
        logo = logo.resize(self.logo_size)

        # Create a copy of image
        webcam_and_logo = webcam.copy()

        # Paste logo onto cam at the specified location
        webcam_and_logo.paste(logo, self.logo_place, logo)

        # Cover old datetime
        corner_rectangle = Image.open('corner-rectangle.png')
        webcam_and_logo.paste(corner_rectangle, None)

        # Add datetime
        draw = ImageDraw.Draw(webcam_and_logo)
        font = ImageFont.truetype("OpenSans-Bold.ttf", 16)
        text_position = (4, 3)
        text_color = (255, 255, 255)
        draw.text(text_position, self.mod_time_str, font=font, fill=text_color)

        # Save logoed file
        webcam_and_logo.save(self.logoed, format="JPEG")
        self.logoed.seek(0)

    def upload_image(self):
        file_path = f'{self.name}.jpg'

        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(os.getenv('username'), os.getenv('password'))

        # Store the file and close connection
        ftp.storbinary('STOR ' + f'{self.name}.jpg', self.logoed)
        ftp.quit()

        self.upload = f'https://glacier.org/webcam/{file_path}'

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
