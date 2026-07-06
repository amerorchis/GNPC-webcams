"""Regression tests for AllskyVideo state handling (no network/FTP)."""

import io
from ftplib import error_perm

import AllskyVideo
from AllskyVideo import AllskyVideo as AllskyVideoClass


def make_video():
    return AllskyVideoClass(
        name="allsky",
        file_name_on_server="allsky.mp4",
        logo_place=(0, 619),
        logo_size=(299, 68),
        username="user",
        password="pwd",
    )


class FakeFTP:
    """Minimal FTP stub whose RETR fails as if the file vanished mid-run."""

    def __init__(self, files):
        self.files = files

    def nlst(self):
        return self.files

    def retrbinary(self, cmd, callback):
        raise error_perm("550 Can't open allsky.mp4: No such file or directory")

    def quit(self):
        pass


def test_get_does_not_crash_when_file_vanishes_after_nlst(monkeypatch):
    """File present at nlst() but gone at RETR should not raise or set available."""
    monkeypatch.setattr(
        AllskyVideo, "connect_ftp", lambda *a, **k: FakeFTP(["allsky.mp4"])
    )

    vid = make_video()
    vid.get()  # Must not raise the 550 error_perm

    assert vid.available is False


def test_upload_image_skips_when_logoed_is_not_a_path():
    """Stale available=True with an unset BytesIO logoed must not crash."""
    vid = make_video()
    vid.available = True  # Simulate stale state from a failed earlier step
    assert isinstance(vid.logoed, io.BytesIO)

    vid.upload_image()  # Must return cleanly, not TypeError on open(BytesIO)
