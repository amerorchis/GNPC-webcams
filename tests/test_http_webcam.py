"""Tests for the HTTP-sourced webcam (no network)."""

import requests

import HttpWebcam as http_webcam_module
from HttpWebcam import HttpWebcam
from Webcam import Webcam


class FakeResponse:
    def __init__(self, content=b"jpeg-bytes", headers=None):
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        pass


def fake_get(response_or_error, calls=None):
    """A requests.get stand-in returning a response, or raising per attempt."""

    def get(url, headers=None, timeout=None):
        if calls is not None:
            calls.append(url)
        if isinstance(response_or_error, list):
            outcome = response_or_error.pop(0)
        else:
            outcome = response_or_error
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return get


def test_download_reads_body_and_timestamp(monkeypatch):
    """The Last-Modified header stands in for the FTP server's MDTM reply."""
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get(
            FakeResponse(headers={"Last-Modified": "Mon, 10 Aug 2026 19:17:09 GMT"})
        ),
    )

    cam = HttpWebcam(name="tm", url="https://example.org/TwoMedicine.jpg")
    cam._download_image()

    assert cam.file_buffer.getvalue() == b"jpeg-bytes"
    # 19:17 UTC is 1:17 pm in Mountain Daylight Time
    assert cam.mod_time_str == "1:17 pm Aug. 10, 2026"


def test_download_retries_then_succeeds(monkeypatch):
    """A flaky fetch must be retried rather than killing the camera."""
    calls = []
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get([requests.ConnectionError("reset by peer"), FakeResponse()], calls),
    )

    cam = HttpWebcam(name="tm", url="https://example.org/TwoMedicine.jpg")
    cam._download_image(retry_delay=0)

    assert len(calls) == 2
    assert cam.file_buffer.getvalue() == b"jpeg-bytes"


def test_missing_last_modified_leaves_a_blank_timestamp(monkeypatch):
    """A header-less response still publishes the image, just undated."""
    monkeypatch.setattr(
        http_webcam_module.requests, "get", fake_get(FakeResponse(headers={}))
    )

    cam = HttpWebcam(name="tm", url="https://example.org/TwoMedicine.jpg")
    cam._download_image()

    assert cam.file_buffer.getvalue() == b"jpeg-bytes"
    assert cam.mod_time_str == ""
    assert cam.mod_time is None


def test_unparseable_last_modified_is_survivable(monkeypatch):
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get(FakeResponse(headers={"Last-Modified": "whenever"})),
    )

    cam = HttpWebcam(name="tm", url="https://example.org/TwoMedicine.jpg")
    cam._download_image()

    assert cam.mod_time_str == ""


def test_upload_connection_is_shared_with_the_ftp_cameras(monkeypatch):
    """The pool lives on Webcam, so _close_connections() releases it.

    Assigning through `cls` instead would give the subclass its own attribute:
    an extra session against a server that counts them, held open until it
    times out because main.py only ever closes Webcam's.
    """
    monkeypatch.setattr(Webcam, "_upload_ftp", None)
    monkeypatch.setattr("Webcam.connect_ftp", lambda *a, **k: "connection")

    assert HttpWebcam._get_upload_connection() == "connection"
    assert Webcam._upload_ftp == "connection"
    assert "_upload_ftp" not in HttpWebcam.__dict__
