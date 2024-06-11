from Webcam import Webcam
import threading
import os
from time import sleep
from send_email import email_alert
from dotenv import load_dotenv

load_dotenv('environment.env')

dark_sky = Webcam(name='dark_sky',
             ip='stmaryallsky-resize.jpg',
             logo_place=(0,619),
             logo_size=(299,68),
             username=os.getenv('darksky_user'),
             password=os.getenv('darksky_pwd'))

cams = [dark_sky]

def handle_cam(cam: Webcam):
    try:
        cam.get()
        cam.add_logo()
        cam.upload_image()
        print(cam.upload)
    except Exception as e:
        error_message = f'{cam.name} failed. {e}'
        print(error_message)
        return error_message

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
        email_alert(error_message)

if __name__ == "__main__":
    for i in range(6):
        main()
        sleep(45)
