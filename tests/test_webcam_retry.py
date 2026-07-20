"""Regression tests for Webcam FTP retry handling (no network)."""

from ftplib import error_temp

import Webcam
from Webcam import Webcam as WebcamClass


class FlakyDownloadFTP:
    """FTP stub whose RETR raises a transient 425 for the first calls."""

    def __init__(self, counter, fail_times):
        self.counter = counter
        self.fail_times = fail_times

    def retrbinary(self, cmd, callback):
        if self.counter[0] < self.fail_times:
            self.counter[0] += 1
            raise error_temp(
                "425 Unable to identify the local data socket: Address already in use"
            )
        callback(b"jpeg-bytes")

    def sendcmd(self, cmd):
        return "213 20240101120000"


def test_download_retries_on_transient_425(monkeypatch):
    """A 425 error_temp must be retried, not propagate and kill the camera."""
    WebcamClass._download_ftp = None
    counter = [0]
    monkeypatch.setattr(
        Webcam, "connect_ftp", lambda *a, **k: FlakyDownloadFTP(counter, fail_times=1)
    )

    cam = WebcamClass(name="hlt", file_name_on_server="hlt.jpg")
    cam._download_image(retry_delay=0)  # Must not raise error_temp

    assert cam.file_buffer.getvalue() == b"jpeg-bytes"
    assert counter[0] == 1  # Failed once, then succeeded on retry

    WebcamClass._download_ftp = None
