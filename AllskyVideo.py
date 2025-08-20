"""
A class to represent the overnight timelapse video.
Inherits from Webcam to maintain the same API.s
"""

import io
import logging
import os
from datetime import datetime, timedelta
from ftplib import FTP, error_perm

import ffmpeg
from dotenv import load_dotenv

from Webcam import Webcam

load_dotenv("environment.env")

logger = logging.getLogger(__name__)


class AllskyVideo(Webcam):
    """
    Overnight timelapse video object. (Could be a singleton with class methods)
    """

    def __init__(
        self, name, file_name_on_server, logo_place, logo_size, username, password
    ):
        self.name = name
        self.file_buffer = io.BytesIO()
        self.logoed = io.BytesIO()

        self.available = False
        self.file_name_on_server = file_name_on_server
        self.logo_place = logo_place
        self.logo_size = logo_size
        self.username = username
        self.password = password

        self.mod_time = None
        self.mod_time_str = ""
        self.upload = None
        self.processed_today = False

    def process(self):
        """
        Process video - override parent method to add daily processing check.
        """
        logger.info(f"{self.name}: Checking if video already processed today...")

        # Check if already processed today before doing anything
        try:
            if self.check_if_processed_today():
                logger.info(f"{self.name}: Video already processed today, skipping")
                return  # Gracefully exit - already processed today
        except Exception as e:
            logger.warning(f"{self.name}: Could not check if processed today: {e}")
            # Continue with processing as fallback

        logger.info(f"{self.name}: Processing video...")
        # Call parent class methods for video processing
        self.get()
        logger.info(f"{self.name}: After get(), available={self.available}")
        if self.available:
            logger.info(f"{self.name}: Video available, proceeding with logo overlay")
            self.add_logo()
        else:
            logger.info(f"{self.name}: No video available, skipping logo overlay")

    def check_if_processed_today(self):
        """
        Check if video has already been processed today by verifying
        if the output file exists on the upload server.
        """
        try:
            # Connect to the upload FTP server
            ftp = FTP(os.getenv("server"))
            ftp.login(os.getenv("username"), os.getenv("password"))

            # Check if our processed video file exists
            files = ftp.nlst()
            video_exists = f"{self.name}.mp4" in files

            if video_exists:
                # Check if it was modified today by getting its modification time
                try:
                    mod_time_str = ftp.voidcmd(f"MDTM {self.name}.mp4")[4:]
                    mod_time = datetime.strptime(mod_time_str, "%Y%m%d%H%M%S")
                    today = datetime.now().date()

                    self.processed_today = mod_time.date() == today
                except Exception:
                    # If we can't get mod time, assume it's processed if file exists
                    self.processed_today = True

            ftp.quit()
            return self.processed_today

        except Exception:
            # If we can't connect or check, assume not processed to be safe
            return False

    def set_mod_time(self, ftp):
        """
        Set the modification time for the video file (same logic as parent class).
        """
        try:
            response = ftp.sendcmd(f"MDTM {self.file_name_on_server}")
            # The response will be in the format: '213 YYYYMMDDHHMMSS'
            if response.startswith("213"):
                time_str = response[4:].strip()
                mod_time = datetime.strptime(time_str, "%Y%m%d%H%M%S") - timedelta(
                    hours=6
                )
                self.mod_time = mod_time
                self.mod_time_str = mod_time.strftime("%-I:%M%p %b. %d, %Y")
        # 550 errors can be ignored
        except error_perm as e:
            if str(e).startswith("550"):
                pass

    def get(self):
        """
        Download overnight timelapse video from FTP server.

        Checks if the video file exists on the server, downloads it to a buffer,
        saves it to disk as 'allsky.mp4', and sets the modification time.
        Sets self.available to True if video is found and downloaded successfully.
        """
        # First check if we've already processed a video today
        if self.check_if_processed_today():
            logger.info(f"{self.name}: Already processed today, marking as unavailable")
            self.available = False  # Explicitly set to False
            return  # Gracefully exit - already processed today

        # Connect to the FTP server
        ftp = FTP(os.getenv("server"))
        ftp.login(self.username, self.password)

        # Check if file is there, if it's not we don't need to do anything else
        # with this
        # object on this round.
        if self.file_name_on_server not in ftp.nlst():
            ftp.quit()
            return

        self.available = True  # Mark that the video was found.

        # Save the file into the buffer.
        ftp.retrbinary(f"RETR {self.file_name_on_server}", self.file_buffer.write)
        self.file_buffer.seek(0)

        self.set_mod_time(ftp)  # Set the file modification time.

        # Save the video to disk
        with open("allsky.mp4", "wb") as allsky:
            allsky.write(self.file_buffer.getvalue())

        # Close the FTP connection
        ftp.quit()

    def add_logo(self):
        """
        Apply logo overlay to the downloaded video using FFmpeg.

        Uses FFmpeg to overlay the logo-shaded-video.png onto the allsky.mp4
        at the configured position and saves the result as 'allsky-logo.mp4'.
        Only processes if self.available is True.
        """
        if not self.available:
            logger.info(f"{self.name}: No video available, skipping logo overlay")
            return

        # Additional check: ensure video file actually exists
        if not os.path.exists("allsky.mp4"):
            logger.warning(f"{self.name}: allsky.mp4 file not found, cannot add logo")
            self.available = False
            return

        logger.info(f"{self.name}: Adding logo to video...")

        # Set up the input and output streams
        input_stream = ffmpeg.input("allsky.mp4")
        logo_stream = ffmpeg.input("overlays/logo-shaded-video.png")
        output_stream = ffmpeg.output(
            input_stream.overlay(
                logo_stream, x=self.logo_place[0], y=self.logo_place[1]
            ),
            "allsky-logo.mp4",
            format="mp4",
        )

        # Run ffmpeg
        ffmpeg.run(
            output_stream,
            overwrite_output=True,
            capture_stdout=True,
            capture_stderr=True,
        )
        self.logoed = "allsky-logo.mp4"  # Path to logo video file.

    def upload_image(self):
        """
        Don't change the name of this even though it's a video not image because
        it works with the same API as the webcams this way.
        """

        # Make sure there is a video to upload
        if not self.available:
            return

        file_path = f"{self.name}.mp4"  # Desired file name on server

        # Connect to the FTP server
        ftp = FTP(os.getenv("server"))
        ftp.login(os.getenv("username"), os.getenv("password"))

        # Store the file and close connection
        with open(self.logoed, "rb") as vid:
            ftp.storbinary("STOR " + f"{self.name}.mp4", vid)
            ftp.quit()

        self.upload = f"https://glacier.org/webcam/{file_path}"  # URL for the video

        # Once it's logoed and uploaded, remove from FTP server.
        self.delete_on_FTP_server()

    def delete_on_FTP_server(self):
        """
        Once video is on HTML server with logo, delete from FTP server so we
        don't keep uploading it.
        """

        # Connect to the FTP server
        ftp = FTP(os.getenv("server"))
        ftp.login(self.username, self.password)

        # Remove the allsky video
        if self.file_name_on_server in ftp.nlst():
            ftp.delete(self.file_name_on_server)

        # Close the FTP connection
        ftp.quit()


if __name__ == "__main__":
    vid = AllskyVideo(
        name="allsky",
        file_name_on_server="allsky.mp4",
        logo_place=(0, 619),
        logo_size=(299, 68),
        username=os.getenv("ftp_get_user"),
        password=os.getenv("ftp_get_pwd"),
    )

    vid.get()
    vid.available = True
    vid.add_logo()
    vid.upload_image()
