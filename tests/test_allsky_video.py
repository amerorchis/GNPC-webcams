"""Regression tests for AllskyVideo state handling (no network/FTP)."""

import io
import socket
from datetime import datetime
from ftplib import error_perm
from zoneinfo import ZoneInfo

import pytest

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


class FlakyConnectFTP:
    """FTP stub that serves a video, after connect_ftp fails a few times."""

    def __init__(self, files):
        self.files = files

    def nlst(self):
        return self.files

    def retrbinary(self, cmd, callback):
        callback(b"mp4-bytes")

    def sendcmd(self, cmd):
        return "213 20240101120000"

    def quit(self):
        pass


def test_get_retries_a_dns_failure(monkeypatch, tmp_path):
    """A DNS blip at connect time must not fail the whole video for the day.

    The still cameras ride these out because their connect failures surface
    inside _download_image's retry loop; the video opens its own connection, so
    without a loop of its own one bad lookup killed it outright.
    """
    attempts = []

    def flaky_connect(*args, **kwargs):
        attempts.append(args)
        if len(attempts) < 3:
            raise socket.gaierror(-3, "Temporary failure in name resolution")
        return FlakyConnectFTP(["allsky.mp4"])

    monkeypatch.setattr(AllskyVideo, "connect_ftp", flaky_connect)

    vid = make_video()
    vid.raw_video_path = str(tmp_path / "allsky-raw.mp4")
    vid.get(retry_delay=0)  # Must not raise gaierror

    assert len(attempts) == 3  # Failed twice, then succeeded
    assert vid.available is True


def test_get_gives_up_after_max_retries(monkeypatch):
    """A network fault that never clears still surfaces, rather than going quiet."""
    attempts = []

    def always_failing_connect(*args, **kwargs):
        attempts.append(args)
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(AllskyVideo, "connect_ftp", always_failing_connect)

    vid = make_video()
    with pytest.raises(socket.gaierror):
        vid.get(retry_delay=0)

    assert len(attempts) == 3
    assert vid.available is False


def test_upload_image_skips_when_logoed_is_not_a_path():
    """Stale available=True with an unset BytesIO logoed must not crash."""
    vid = make_video()
    vid.available = True  # Simulate stale state from a failed earlier step
    assert isinstance(vid.logoed, io.BytesIO)

    vid.upload_image()  # Must return cleanly, not TypeError on open(BytesIO)


class PublishedFTP:
    """Upload-server stub that already holds today's video."""

    def __init__(self, mdtm_utc):
        self.mdtm_utc = mdtm_utc

    def nlst(self):
        return ["allsky.mp4"]

    def voidcmd(self, cmd):
        return f"213 {self.mdtm_utc}"

    def quit(self):
        pass


def test_processed_today_compares_dates_in_mountain_time(monkeypatch):
    """An evening upload is 'tomorrow' in UTC but still today on the Pi.

    01:30 UTC on the 22nd is 7:30 pm MDT on the 21st; a run at 8 pm must see
    the video as already done rather than go looking for it again.
    """
    monkeypatch.setattr(
        AllskyVideo, "connect_ftp", lambda *a, **k: PublishedFTP("20260822013000")
    )
    now = datetime(2026, 8, 21, 20, 0, tzinfo=ZoneInfo("America/Denver"))

    assert make_video().check_if_processed_today(now=now) is True


def test_yesterdays_video_does_not_count_as_processed(monkeypatch):
    monkeypatch.setattr(
        AllskyVideo, "connect_ftp", lambda *a, **k: PublishedFTP("20260821013000")
    )
    now = datetime(2026, 8, 21, 20, 0, tzinfo=ZoneInfo("America/Denver"))

    assert make_video().check_if_processed_today(now=now) is False
