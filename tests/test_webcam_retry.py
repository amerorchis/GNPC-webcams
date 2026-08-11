"""Regression tests for Webcam FTP retry handling (no network)."""

import io
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


class VanishingFileFTP:
    """FTP stub whose RETR 550s while the frame is being replaced upstream.

    Writes a partial frame before failing, the way a server that deletes the
    file mid-transfer would.
    """

    def __init__(self, counter, fail_times):
        self.counter = counter
        self.fail_times = fail_times

    def retrbinary(self, cmd, callback):
        if self.counter[0] < self.fail_times:
            self.counter[0] += 1
            callback(b"half-a-")
            raise error_perm("550 Can't open dark_sky.jpg: No such file or directory")
        callback(b"jpeg-bytes")

    def sendcmd(self, cmd):
        return "213 20240101120000"


def test_missing_file_is_retried_for_every_attempt(monkeypatch):
    """The frame is swapped in place, so a 550 is usually gone a second later."""
    WebcamClass._download_ftp = None
    counter = [0]
    monkeypatch.setattr(
        Webcam,
        "connect_ftp",
        lambda *a, **k: VanishingFileFTP(counter, fail_times=2),
    )

    cam = WebcamClass(name="dark_sky", file_name_on_server="stmaryallsky-resize.jpg")
    cam._download_image(retry_delay=0)  # Must not raise FileNotFoundError

    assert counter[0] == 2  # Two 550s ridden out, not just one
    # The bytes from the failed attempts are dropped instead of being prepended
    # to the frame that finally arrives.
    assert cam.file_buffer.getvalue() == b"jpeg-bytes"

    WebcamClass._download_ftp = None


def test_a_file_that_never_appears_still_fails(monkeypatch):
    """A source that is genuinely gone has to reach the cron email."""
    WebcamClass._download_ftp = None
    counter = [0]
    monkeypatch.setattr(
        Webcam,
        "connect_ftp",
        lambda *a, **k: VanishingFileFTP(counter, fail_times=99),
    )

    cam = WebcamClass(name="dark_sky", file_name_on_server="stmaryallsky-resize.jpg")
    with pytest.raises(FileNotFoundError):
        cam._download_image(retry_delay=0)

    assert counter[0] == 3  # Every attempt used before giving up

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


class HangingUpFTP:
    """FTP stub that hangs up on the first upload, the way a dropped session does.

    ftplib turns a control connection closed mid-reply into EOFError, so this is
    what a pooled connection the server has given up on looks like from here.
    """

    def __init__(self, counter, fail_times):
        self.counter = counter
        self.fail_times = fail_times
        self.stored = []

    def storbinary(self, cmd, fp):
        if self.counter[0] < self.fail_times:
            self.counter[0] += 1
            raise EOFError
        self.stored.append(cmd)

    def rename(self, src, dst):
        pass

    def quit(self):
        pass


class SingleOverlay:
    """Stands in for a Logo/overlay that already has its rendered image."""

    def get_overlayed_img(self, name):
        return io.BytesIO(b"jpeg-bytes"), f"{name}.jpg"


def test_upload_retries_when_the_server_hangs_up(monkeypatch):
    """EOFError is not an OSError, so it needs naming to reach the retry path.

    A dropped control connection is the ordinary way a pooled session dies
    between uses; reconnecting is exactly what the retry loop is for.
    """
    WebcamClass._upload_ftp = None
    counter = [0]
    monkeypatch.setattr(
        Webcam, "connect_ftp", lambda *a, **k: HangingUpFTP(counter, fail_times=1)
    )

    cam = WebcamClass(name="lpp", file_name_on_server="lpp.jpg")
    cam.overlays = [SingleOverlay()]
    cam.upload_image(retry_delay=0)  # Must not raise EOFError

    assert counter[0] == 1  # Hung up once, then succeeded on a fresh connection
    assert cam.upload == ["https://glacier.org/webcam/lpp.jpg"]

    WebcamClass._upload_ftp = None


def test_download_retries_when_the_server_hangs_up(monkeypatch):
    """The same dropped-session EOFError on the download pool."""

    class HangingUpDownloadFTP:
        def __init__(self, counter, fail_times):
            self.counter = counter
            self.fail_times = fail_times

        def retrbinary(self, cmd, callback):
            if self.counter[0] < self.fail_times:
                self.counter[0] += 1
                raise EOFError
            callback(b"jpeg-bytes")

        def sendcmd(self, cmd):
            return "213 20240101120000"

        def quit(self):
            pass

    WebcamClass._download_ftp = None
    counter = [0]
    monkeypatch.setattr(
        Webcam,
        "connect_ftp",
        lambda *a, **k: HangingUpDownloadFTP(counter, fail_times=1),
    )

    cam = WebcamClass(name="lpp", file_name_on_server="lpp.jpg")
    cam._download_image(retry_delay=0)  # Must not raise EOFError

    assert cam.file_buffer.getvalue() == b"jpeg-bytes"
    assert counter[0] == 1

    WebcamClass._download_ftp = None


def test_a_hangup_does_not_downgrade_the_run_to_plain_ftp(monkeypatch):
    """A dropped socket is not a verdict on TLS support.

    Latching _ftps_supported to False would send every later login in this run's
    credentials in the clear over one transient hangup.
    """

    class HangingUpFTPS:
        def __init__(self, server, timeout=None):
            raise EOFError

    def unexpected_plain_ftp(*args, **kwargs):
        raise AssertionError("plain FTP must not be attempted after a hangup")

    monkeypatch.setattr(Webcam, "_ftps_supported", None)
    monkeypatch.setattr(Webcam, "FTP_TLS", HangingUpFTPS)
    monkeypatch.setattr(Webcam, "FTP", unexpected_plain_ftp)

    with pytest.raises(EOFError):
        Webcam.connect_ftp("host", "user", "pwd")

    assert Webcam._ftps_supported is None  # Still unknown, not ruled out


def test_connection_limit_gets_a_longer_backoff():
    """Retrying a full server at the normal cadence just re-trips the limit."""
    busy = error_temp("421 Too many connections (8) from this IP")
    other = error_temp("425 Unable to identify the local data socket")

    assert Webcam.retry_delay_for(2, 0, busy) > Webcam.retry_delay_for(2, 0, other)
