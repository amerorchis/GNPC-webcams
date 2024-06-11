import io
import os
from ftplib import FTP

from dotenv import load_dotenv
from PIL import Image

load_dotenv('environment.env')

class Webcam:
    def __init__(self, name, ip, logo_place, logo_size, username=None, password=None):
        self.name = name
        self.file_buffer = io.BytesIO()
        self.url = ip
        self.logo_place = logo_place
        self.logo_size = logo_size
        self.username = username
        self.password = password
        self.logoed = None
        self.upload = None

    def get(self):
        # Connect to the FTP server
        ftp = FTP(os.getenv('server'))
        ftp.login(self.username, self.password)
        # print(ftp.nlst())
        def handle_binary(data):
            self.file_buffer.write(data)

        ftp.retrbinary(f'RETR {self.url}', handle_binary)

        self.file_buffer.seek(0)

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

        try:
            # Open the local file in binary mode
            with open(self.logoed, 'rb') as f:
                # Upload the file to the FTP server
                ftp.storbinary('STOR ' + file_path, f)

        except:
            print('Failed upload')
            pass

        # Close the FTP connection
        ftp.quit()

        self.upload = f'https://glacier.org/webcam/{file_path}'
