from datetime import datetime
from ftplib import FTP
import os
from dotenv import load_dotenv

load_dotenv('environment.env')

def upload_ftp(webcam):
    today = datetime.now()
    file_path = f'{webcam.name}.jpg'

    # Connect to the FTP server
    ftp = FTP(os.getenv('server'))
    ftp.login(os.getenv('username'), os.getenv('password'))

    try:
        # Open the local file in binary mode
        with open(webcam.logoed, 'rb') as f:
            # Upload the file to the FTP server
            ftp.storbinary('STOR ' + file_path, f)

    except:
        print('Failed upload')
        pass

    # Close the FTP connection
    ftp.quit()

    return f'https://glacier.org/webcam/{file_path}'
