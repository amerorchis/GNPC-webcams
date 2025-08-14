#! /usr/bin/python3

"""
Controls the operation of the program to add logos to and upload webcam photos and videos
from the glacier.org FTP server to HTML server.
"""

import logging
import threading
import traceback
from time import sleep

from dotenv import load_dotenv
from logging_config import setup_logging

load_dotenv("environment.env")
setup_logging()
logger = logging.getLogger(__name__)

from config import (
    load_config,
    create_webcam_from_config,
    create_allsky_video_from_config,
)
from Webcam import Webcam

# Load configuration from YAML
app_config = load_config("webcams.yaml")

# Create webcam objects from configuration
webcams = [
    create_webcam_from_config(webcam_config) for webcam_config in app_config.webcams
]
allsky_videos = [
    create_allsky_video_from_config(video_config)
    for video_config in app_config.allsky_videos
]

# Combine all cameras
cams = webcams + allsky_videos


def handle_cam(cam: Webcam):
    try:
        logger.info(f"Starting processing for {cam.name}...")
        cam.process()
        cam.upload_image()
        logger.info(f"Completed {cam.name}")

    except Exception:
        return f"{cam.name} failed. {traceback.format_exc()}"


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
        error_message = "\n\n".join(errors)
        print(error_message)  # Printing will trigger cron to send an email


if __name__ == "__main__":
    for i in range(2):
        main()
        sleep(45)
