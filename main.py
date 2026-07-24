#! /usr/bin/python3

"""
Controls the operation of the program to add logos to and upload webcam photos
and videos from the glacier.org FTP server to HTML server.
"""

import logging
import sys
import threading
import traceback
from time import sleep

from dotenv import load_dotenv

from logging_config import setup_logging
from paths import resolve_path

load_dotenv(resolve_path("environment.env"))
setup_logging()
logger = logging.getLogger(__name__)

from config import (
    create_allsky_video_from_config,
    create_webcam_from_config,
    load_config,
)
from single_instance import AlreadyRunning, SingleInstance
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

# Seconds to idle between the two rounds of a run. Cron fires every minute and
# only one run executes at a time, so a run has to finish inside its minute or
# the next tick is skipped by the lock. Two rounds plus this gap must leave room
# for the slowest round.
ROUND_INTERVAL = 25


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
        # stderr so cron emails errors even when stdout is redirected to /dev/null
        print(error_message, file=sys.stderr)


if __name__ == "__main__":
    try:
        with SingleInstance():
            try:
                for i in range(2):
                    if i:
                        # Idle between rounds without holding FTP sessions. The
                        # server allows only a few connections per IP, so a
                        # process that sits on its connections while sleeping
                        # starves anything else using them.
                        Webcam._close_connections()
                        sleep(ROUND_INTERVAL)
                    main()
            finally:
                Webcam._close_connections()
    except AlreadyRunning as e:
        # Not an error: the previous run is still working and the next cron tick
        # will cover this cycle. Stays off stderr so cron doesn't email it.
        logger.info(f"Skipping run: {e}")
