"""
A class to represent the overnight timelapse video. Inherits from Webcam to maintain the same API.s
"""

import io
import os
from ftplib import FTP

from dotenv import load_dotenv
import ffmpeg
from Webcam import Webcam

load_dotenv("environment.env")


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

    def get(self):
        # Connect to the FTP server
        ftp = FTP(os.getenv("server"))
        ftp.login(self.username, self.password)

        # Check if file is there, if it's not we don't need to do anything else with this
        # object on this round.
        if self.file_name_on_server not in ftp.nlst():
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
        if not self.available:
            return

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
