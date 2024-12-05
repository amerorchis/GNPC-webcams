#! /usr/bin/python3

"""
Controls the operation of the program to add logos to and upload webcam photos and videos
from the glacier.org FTP server to HTML server.
"""

import os
import threading
import traceback
from time import sleep

from dotenv import load_dotenv

from AllskyVideo import AllskyVideo
from Webcam import Webcam, Logo

load_dotenv('environment.env')

depot = Webcam(name='depot',
            file_name_on_server='depot.jpg',
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'),
            logo_placements=[
                Logo(
                    place=(0,0),
                    size=(1,1),
                    cover_date=False)
            ])

dso_camera = Webcam(name='dark_sky',
            file_name_on_server='stmaryallsky-resize.jpg',
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'),
            logo_placements=[
                Logo(
                    place=(0,604),
                    size=(299,68),
                    subname='nps',
                    cover_date=True),
                Logo(
                    place=(0,619),
                    size=(299,68),
                    cover_date=True)
            ])

lpp = Webcam(name='lpp',
            file_name_on_server='lpp.jpg',
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'),
            logo_placements=[
                Logo(
                    place=(1507,10),
                    size=(531,88),
                    img='logo.png',
                    subname='nps'
                ),
                Logo(
                    place=(0, 1400),
                    size=(612,137),
                    img='logo-shaded.png',
                ),
            ])

smv = Webcam(name='smv',
            file_name_on_server='smv.jpg',
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'),
            logo_placements=[
                Logo(
                    place=(140,944),
                    size=(612,137),
                    img='logo-shaded.png',
                    subname='nps'
                ),
                Logo(
                    place=(0,944),
                    size=(612,137),
                    img='logo-shaded.png',
                ),
            ])

hlt = Webcam(name='hlt',
            file_name_on_server='hlt.jpg',
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'),
            logo_placements=[
                Logo(
                    place=(140,944),
                    size=(612,137),
                    img='logo-shaded.png',
                    subname='nps'
                ),
                Logo(
                    place=(0,944),
                    size=(612,137),
                    img='logo-shaded.png',
                ),
            ])

stuck = Webcam(name='stuck',
            file_name_on_server='stuck.jpg',
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'),
            logo_placements=[
                Logo(
                    place=(0,944),
                    size=(612,137),
                    img='logo-shaded.png',
                ),
            ])

dso_timelapse = AllskyVideo(
            name='allsky',
            file_name_on_server='allsky.mp4',
            logo_place=(0,619),
            logo_size=(299,68),
            username=os.getenv('ftp_get_user'),
            password=os.getenv('ftp_get_pwd'))

cams = [depot, dso_camera, lpp, smv, hlt, stuck, dso_timelapse]

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
