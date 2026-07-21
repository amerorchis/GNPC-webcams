"""Regression tests for Webcam FTP retry handling (no network)."""

from ftplib import error_perm, error_temp

import pytest

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


def test_download_closes_stale_connection_before_reconnecting():
    """A dead shared connection must be QUIT, not just dropped.

    The server counts sessions, not sockets: an abandoned connection keeps its
    slot until an idle timeout, which is how the pool drifts into "421 Too many
    connections".
    """
    quit_calls = []

    class DeadFTP:
        def retrbinary(self, cmd, callback):
            raise BrokenPipeError("connection lost")

        def quit(self):
            quit_calls.append(self)

    WebcamClass._download_ftp = DeadFTP()
    cam = WebcamClass(name="hlt", file_name_on_server="hlt.jpg")

    try:
        cam._download_image(max_retries=1, retry_delay=0)
    except BrokenPipeError:
        pass
    else:  # pragma: no cover - the stub always fails
        raise AssertionError("expected the download to fail")

    assert len(quit_calls) == 1
    assert WebcamClass._download_ftp is None


class RefusingFTPS:
    """FTP_TLS stub whose greeting is the server's connection-limit refusal."""

    instances = []

    def __init__(self, server, timeout=None):
        RefusingFTPS.instances.append(self)
        raise error_temp("421 Too many connections (8) from this IP")


def test_connection_limit_does_not_trigger_plain_ftp_fallback(monkeypatch):
    """421 means the server is full, not that it lacks TLS.

    Falling back to plain FTP would open a second socket that fails the same
    way, doubling the connection attempts exactly when the IP is over its limit.
    """
    plain_attempts = []

    def unexpected_plain_ftp(*args, **kwargs):
        plain_attempts.append(args)
        raise AssertionError("plain FTP must not be attempted after a 421")

    monkeypatch.setattr(Webcam, "_ftps_supported", None)
    monkeypatch.setattr(Webcam, "FTP_TLS", RefusingFTPS)
    monkeypatch.setattr(Webcam, "FTP", unexpected_plain_ftp)
    RefusingFTPS.instances.clear()

    with pytest.raises(error_temp):
        Webcam.connect_ftp("host", "user", "pwd")

    assert plain_attempts == []


def test_ftps_failure_closes_socket_and_is_only_probed_once(monkeypatch):
    """A server without TLS should cost one failed FTPS probe, not one per connect."""
    closed = []
    probes = []

    class NoTLSFTPS:
        def __init__(self, server, timeout=None):
            probes.append(server)

        def login(self, user, password):
            raise error_perm("500 AUTH not understood")

        def quit(self):
            closed.append(self)

    class PlainFTP:
        def __init__(self, server, timeout=None):
            pass

        def login(self, user, password):
            pass

    monkeypatch.setattr(Webcam, "_ftps_supported", None)
    monkeypatch.setattr(Webcam, "FTP_TLS", NoTLSFTPS)
    monkeypatch.setattr(Webcam, "FTP", PlainFTP)

    for _ in range(3):
        assert isinstance(Webcam.connect_ftp("host", "user", "pwd"), PlainFTP)

    assert len(probes) == 1  # FTPS support is remembered, not re-probed
    assert len(closed) == 1  # and the failed probe released its connection


def test_connection_limit_gets_a_longer_backoff():
    """Retrying a full server at the normal cadence just re-trips the limit."""
    busy = error_temp("421 Too many connections (8) from this IP")
    other = error_temp("425 Unable to identify the local data socket")

    assert Webcam.retry_delay_for(2, 0, busy) > Webcam.retry_delay_for(2, 0, other)
