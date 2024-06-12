import io
import os
from time import sleep
from ftplib import FTP
from datetime import datetime

from dotenv import load_dotenv
from PIL import Image

load_dotenv('environment.env')

class Webcam:
    def __init__(self, name, file_name_on_server, logo_place, logo_size, username=None, password=None):
        self.name = name
        self.file_buffer = io.BytesIO()
        self.file_name_on_server = file_name_on_server
        self.logo_place = logo_place
        self.logo_size = logo_size
        self.username = username
        self.password = password
        self.mod_time = None
        self.logoed = None
        self.upload = None

    def get(self):
        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(self.username, self.password)

        # Check if file is there, if it's not it may just need a few seconds to finish uploading.
        if self.file_name_on_server not in ftp.nlst():
            sleep(6)
            if self.file_name_on_server not in ftp.nlst():
                raise FileNotFoundError(f"{self.name} wasn't found in the folder.")

        # Save the file into the buffer.
        ftp.retrbinary(f'RETR {self.file_name_on_server}', self.file_buffer.write)
        self.file_buffer.seek(0)

        self.set_mod_time(ftp) # Set the file modification time.

        # Close the FTP connection
        ftp.quit()

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

        path = f'images/{self.name}_logo.jpg'

        webcam_and_logo.save(path)
        self.logoed = path

    def upload_image(self):
        file_path = f'{self.name}.jpg'

        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(os.getenv('username'), os.getenv('password'))

        # Open the local file in binary mode
        with open(self.logoed, 'rb') as f:
            # Upload the file to the FTP server
            ftp.storbinary('STOR ' + file_path, f)

        # Close the FTP connection
        ftp.quit()

        self.upload = f'https://glacier.org/webcam/{file_path}'

    def set_mod_time(self, ftp: FTP):
        # Send the MDTM command to the FTP server
        response = ftp.sendcmd(f"MDTM {self.file_name_on_server}")

        # The response will be in the format: '213 YYYYMMDDHHMMSS'
        if response.startswith('213'):
            time_str = response[4:].strip()
            mod_time = datetime.strptime(time_str, '%Y%m%d%H%M%S')
            self.mod_time = mod_time
