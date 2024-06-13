import os
import threading
import traceback
from time import sleep

from dotenv import load_dotenv

from AllskyVideo import AllskyVideo
from Webcam import Webcam

load_dotenv('environment.env')

dark_sky = Webcam(name='dark_sky',
            file_name_on_server='stmaryallsky-resize.jpg',
            logo_place=(0,619),
            logo_size=(299,68),
            username=os.getenv('darksky_user'),
            password=os.getenv('darksky_pwd'))

allsky = AllskyVideo(
            name='allsky',
            file_name_on_server='allsky.mp4',
            logo_place=(0,619),
            logo_size=(299,68),
            username=os.getenv('darksky_user'),
            password=os.getenv('darksky_pwd'))

cams = [dark_sky, allsky]

def handle_cam(cam: Webcam):
    try:
        cam.get()
        cam.add_logo()
        cam.upload_image()

    except Exception:
        return f'{cam.name} failed. {traceback.format_exc()}'

def main():
    threads = []
    errors = []

    for cam in cams:
        thread = threading.Thread(target=lambda cam=cam: errors.append(handle_cam(cam)))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    errors = [item for item in errors if item is not None]
    if errors:
        error_message = '\n\n'.join(errors)
        print(error_message) # Printing will trigger cron to send an email

if __name__ == "__main__":
    for i in range(2):
        main()
        sleep(45)
