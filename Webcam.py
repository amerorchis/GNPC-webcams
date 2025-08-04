"""
Custom class to represent an individual webcam.
"""

import io
import os
from time import sleep
from ftplib import FTP, error_perm
from datetime import datetime, timedelta
from typing import List

from dotenv import load_dotenv
from Overlays import Overlay

load_dotenv('environment.env')

class Webcam:
    def __init__(self, name, file_name_on_server, overlays: List[Overlay] = None, logo_placements: List[Overlay] = None, username=None, password=None):
        self.name = name
        self.file_buffer = io.BytesIO()

        self.file_name_on_server = file_name_on_server
        
        # Handle backward compatibility
        if overlays is not None and logo_placements is not None:
            raise ValueError("Cannot specify both 'overlays' and 'logo_placements'. Use 'overlays' for new code.")
        
        if logo_placements is not None:
            # Backward compatibility
            self.overlays = logo_placements
            self.logo_placements = logo_placements  # Keep for backward compatibility
        else:
            self.overlays = overlays or []
            self.logo_placements = self.overlays  # Keep for backward compatibility
        
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

    def add_overlays(self):
        """Add all overlays to the image."""
        for overlay in self.overlays:
            overlay.add_overlay(self.file_buffer, self.mod_time_str)
    
    def add_logo(self):
        """Backward compatibility method."""
        return self.add_overlays()

    def upload_image(self):
        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(os.getenv('username'), os.getenv('password'))

        for overlay in self.overlays:
            # Get file and name for each overlay.
            overlayed, file_name = overlay.get_overlayed_img(self.name)

            # Store the file
            ftp.storbinary('STOR ' + file_name, overlayed)
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