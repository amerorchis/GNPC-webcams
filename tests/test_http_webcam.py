"""Tests for the HTTP-sourced webcam (no network)."""

import io
import json

import pytest
import requests
from PIL import Image

import HttpWebcam as http_webcam_module
from HttpWebcam import HttpWebcam
from Webcam import Webcam


def tiny_jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 0)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = tiny_jpeg()


@pytest.fixture(autouse=True)
def validators_in_tmp(monkeypatch, tmp_path):
    """Keep each test's validator record out of the real temp dir."""
    monkeypatch.setattr(
        http_webcam_module.tempfile, "gettempdir", lambda: str(tmp_path)
    )
    return tmp_path


class FakeResponse:
    def __init__(self, content=JPEG, headers=None, status_code=200):
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self):
        pass


def fake_get(response_or_error, calls=None, calls_record_headers=False):
    """A requests.get stand-in returning a response, or raising per attempt."""

    def get(url, headers=None, timeout=None):
        if calls is not None:
            calls.append(headers if calls_record_headers else url)
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

    assert cam.file_buffer.getvalue() == JPEG
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
    assert cam.file_buffer.getvalue() == JPEG


def test_missing_last_modified_leaves_a_blank_timestamp(monkeypatch):
    """A header-less response still publishes the image, just undated."""
    monkeypatch.setattr(
        http_webcam_module.requests, "get", fake_get(FakeResponse(headers={}))
    )

    cam = HttpWebcam(name="tm", url="https://example.org/TwoMedicine.jpg")
    cam._download_image()

    assert cam.file_buffer.getvalue() == JPEG
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


URL = "https://example.org/TwoMedicine.jpg"
VALIDATED = FakeResponse(
    headers={
        "Last-Modified": "Mon, 10 Aug 2026 19:17:09 GMT",
        "ETag": '"abc123"',
    }
)


def publish(cam, monkeypatch):
    """Download and 'upload' without FTP, the way a run does."""
    monkeypatch.setattr(cam, "_process_overlay_files", lambda action: None)
    cam._download_image()
    cam.upload_image()


def test_validators_are_sent_back_once_a_frame_has_been_published(monkeypatch):
    """The second fetch asks the server whether anything changed."""
    sent = []
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get([VALIDATED, FakeResponse(status_code=304)], sent, True),
    )
    cam = HttpWebcam(name="tm", url=URL)

    publish(cam, monkeypatch)
    assert "If-None-Match" not in sent[0]  # Nothing published yet

    cam._download_image()
    assert sent[1]["If-None-Match"] == '"abc123"'
    assert sent[1]["If-Modified-Since"] == "Mon, 10 Aug 2026 19:17:09 GMT"
    assert cam.source_unchanged is True


def test_an_unchanged_source_is_neither_processed_nor_uploaded(monkeypatch):
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get([VALIDATED, FakeResponse(status_code=304)]),
    )
    cam = HttpWebcam(name="tm", url=URL)
    publish(cam, monkeypatch)

    applied, uploaded = [], []
    monkeypatch.setattr(cam, "_apply_overlays", lambda: applied.append(1))
    monkeypatch.setattr(cam, "_process_overlay_files", lambda a: uploaded.append(1))
    cam.process()
    cam.upload_image()

    assert cam.source_unchanged is True
    assert applied == [] and uploaded == []
    assert cam.upload == []


def test_validators_are_only_recorded_after_a_successful_upload(
    monkeypatch, validators_in_tmp
):
    """A frame that never reached glacier.org must be fetched again, not skipped."""
    monkeypatch.setattr(http_webcam_module.requests, "get", fake_get(VALIDATED))
    cam = HttpWebcam(name="tm", url=URL)
    cam._download_image()

    def failing_upload(action):
        raise EOFError("server hung up")

    monkeypatch.setattr(cam, "_process_overlay_files", failing_upload)
    with pytest.raises(EOFError):
        cam.upload_image()

    assert not (validators_in_tmp / "gnpc-http-tm.json").exists()
    assert cam._conditional_headers() == {}


def test_validators_for_another_url_are_ignored(validators_in_tmp):
    """Re-pointing a camera must not make its first fetch look unmodified."""
    (validators_in_tmp / "gnpc-http-tm.json").write_text(
        json.dumps({"url": "https://example.org/old.jpg", "etag": '"abc123"'})
    )
    cam = HttpWebcam(name="tm", url=URL)
    assert cam._conditional_headers() == {}


def test_a_fresh_frame_resets_the_unchanged_flag(monkeypatch):
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get([VALIDATED, FakeResponse(status_code=304), VALIDATED]),
    )
    cam = HttpWebcam(name="tm", url=URL)
    publish(cam, monkeypatch)
    cam._download_image()
    assert cam.source_unchanged is True

    cam._download_image()
    assert cam.source_unchanged is False
    assert cam.file_buffer.getvalue() == JPEG


@pytest.mark.parametrize(
    "body, content_type",
    [
        (b"", "image/jpeg"),  # nps.gov has published zero-byte frames
        (b"<html>maintenance</html>", "text/html"),
    ],
)
def test_a_body_that_is_not_an_image_is_skipped_not_raised(
    monkeypatch, validators_in_tmp, caplog, body, content_type
):
    """The published frame stays up and the run does not report a failure."""
    bad = FakeResponse(
        content=body,
        headers={**VALIDATED.headers, "Content-Type": content_type},
    )
    monkeypatch.setattr(http_webcam_module.requests, "get", fake_get(bad))
    cam = HttpWebcam(name="tm", url=URL)

    applied, uploaded = [], []
    monkeypatch.setattr(cam, "_apply_overlays", lambda: applied.append(1))
    monkeypatch.setattr(cam, "_process_overlay_files", lambda a: uploaded.append(1))
    with caplog.at_level("WARNING"):
        cam.process()
    cam.upload_image()

    assert cam.source_unchanged is True
    assert applied == [] and uploaded == []
    assert "not an image" in caplog.text


def test_a_rejected_body_is_not_fetched_again_until_it_changes(monkeypatch):
    """Its validators are recorded so the next fetch can answer 304."""
    empty = FakeResponse(content=b"", headers=VALIDATED.headers)
    sent = []
    monkeypatch.setattr(
        http_webcam_module.requests,
        "get",
        fake_get([empty, FakeResponse(status_code=304), VALIDATED], sent, True),
    )
    cam = HttpWebcam(name="tm", url=URL)

    cam._download_image()
    cam._download_image()
    assert sent[1]["If-None-Match"] == '"abc123"'
    assert cam.source_unchanged is True

    # A replacement object carries a new ETag, so the source answers 200 again.
    cam._download_image()
    assert cam.source_unchanged is False
    assert cam.file_buffer.getvalue() == JPEG
