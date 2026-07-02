"""
A class to represent the overnight timelapse video.
Inherits from Webcam to maintain the same API.
"""

import io
import logging
import os
from datetime import datetime

import ffmpeg
from dotenv import load_dotenv

from paths import resolve_path
from Webcam import Webcam, connect_ftp

load_dotenv(resolve_path("environment.env"))

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

        # Local working files, unique per instance so multiple videos
        # processed in parallel threads don't clobber each other.
        self.raw_video_path = resolve_path(f"{name}-raw.mp4")
        self.logoed_video_path = resolve_path(f"{name}-logo.mp4")

        self.mod_time = None
        self.mod_time_str = ""
        self.upload = None
        self.processed_today = False

    def process(self):
        """
        Process video - override parent method to add daily processing check.
        """
        logger.info(f"{self.name}: Checking if video already processed today...")

        try:
            if self.check_if_processed_today():
                logger.info(f"{self.name}: Video already processed today, skipping")
                return  # Gracefully exit - already processed today
        except Exception as e:
            logger.warning(f"{self.name}: Could not check if processed today: {e}")
            # Continue with processing as fallback

        logger.info(f"{self.name}: Processing video...")
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
            ftp = connect_ftp(
                os.getenv("server"), os.getenv("username"), os.getenv("password")
            )

            try:
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

                return self.processed_today
            finally:
                ftp.quit()

        except Exception:
            # If we can't connect or check, assume not processed to be safe
            return False

    def get(self):
        """
        Download overnight timelapse video from FTP server.

        Checks if the video file exists on the server, downloads it to a buffer,
        saves it to disk, and sets the modification time.
        Sets self.available to True if video is found and downloaded successfully.
        """
        # Connect to the FTP server
        ftp = connect_ftp(os.getenv("server"), self.username, self.password)

        try:
            # Check if file is there, if it's not we don't need to do anything else
            # with this object on this round.
            if self.file_name_on_server not in ftp.nlst():
                return

            self.available = True  # Mark that the video was found.

            # Save the file into the buffer.
            ftp.retrbinary(f"RETR {self.file_name_on_server}", self.file_buffer.write)
            self.file_buffer.seek(0)

            self._set_modification_time(ftp)  # Set the file modification time.

            # Save the video to disk
            with open(self.raw_video_path, "wb") as allsky:
                allsky.write(self.file_buffer.getvalue())
        finally:
            ftp.quit()

    def add_logo(self):
        """
        Apply logo overlay to the downloaded video using FFmpeg.

        Uses FFmpeg to overlay the logo-shaded-video.png onto the raw video
        at the configured position and saves the result to disk.
        Only processes if self.available is True.
        """
        if not self.available:
            logger.info(f"{self.name}: No video available, skipping logo overlay")
            return

        # Additional check: ensure video file actually exists
        if not os.path.exists(self.raw_video_path):
            logger.warning(
                f"{self.name}: {self.raw_video_path} not found, cannot add logo"
            )
            self.available = False
            return

        logger.info(f"{self.name}: Adding logo to video...")

        # Set up the input and output streams
        input_stream = ffmpeg.input(self.raw_video_path)
        logo_stream = ffmpeg.input(resolve_path("overlays/logo-shaded-video.png"))
        output_stream = ffmpeg.output(
            input_stream.overlay(
                logo_stream, x=self.logo_place[0], y=self.logo_place[1]
            ),
            self.logoed_video_path,
            format="mp4",
        )

        # Run ffmpeg
        ffmpeg.run(
            output_stream,
            overwrite_output=True,
            capture_stdout=True,
            capture_stderr=True,
        )
        self.logoed = self.logoed_video_path  # Path to logo video file.

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
        ftp = connect_ftp(
            os.getenv("server"), os.getenv("username"), os.getenv("password")
        )

        try:
            # Store the file atomically and close connection
            with open(self.logoed, "rb") as vid:
                # Atomic file replacement: upload to temporary file first
                temp_name = f"{self.name}.mp4.tmp"
                ftp.storbinary("STOR " + temp_name, vid)

                try:
                    # Atomically rename to final name
                    ftp.rename(temp_name, f"{self.name}.mp4")
                except Exception as rename_error:
                    # Clean up temp file if rename fails
                    try:
                        ftp.delete(temp_name)
                    except Exception:
                        pass  # Ignore cleanup errors
                    raise rename_error
        finally:
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
        ftp = connect_ftp(os.getenv("server"), self.username, self.password)

        try:
            # Remove the allsky video
            if self.file_name_on_server in ftp.nlst():
                ftp.delete(self.file_name_on_server)
        finally:
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
