"""
Custom class to represent an individual webcam.
"""

import io
import logging
import os
import random
import socket
import threading
from datetime import datetime
from ftplib import FTP, FTP_TLS, error_perm, error_temp
from time import sleep
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

from Overlays import CompositeOverlay
from paths import resolve_path

logger = logging.getLogger(__name__)

load_dotenv(resolve_path("environment.env"))


# The server allows only a handful of simultaneous connections per IP, so every
# socket this process opens has to be accounted for. Once a connect attempt tells
# us whether the server speaks explicit TLS, remember the answer: re-probing on
# every connect would double the sockets opened by each camera thread.
_ftps_supported = None


def close_ftp(ftp):
    """Release an FTP connection, sending QUIT if the server is still listening.

    Dropping the reference is not enough — without a QUIT the server keeps the
    session (and its connection slot) until an idle timeout expires.
    """
    if ftp is None:
        return
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


def _is_connection_limit_error(error):
    """True for the server's "421 Too many connections from this IP" refusal."""
    return "too many connections" in str(error).lower()


# Network faults worth reconnecting and retrying for, rather than failing the
# camera. OSError covers the socket failures (broken pipe, reset, refused, and
# DNS via socket.gaierror); error_temp covers transient 4xx replies such as a
# 425 when the server can't open a passive data socket. EOFError has to be named
# separately: it descends from Exception, not OSError, and it is what ftplib
# raises when the server hangs up mid-reply — the usual way a pooled control
# connection dies between uses.
RETRYABLE_FTP_ERRORS = (OSError, EOFError, error_temp)


def retry_delay_for(base_delay, attempt, error):
    """How long to wait before the next FTP retry.

    Backs off further each attempt, stretches the wait when the server is
    refusing connections outright (nothing will succeed until other threads let
    go of their slots), and jitters so the camera threads don't all come back at
    the same instant and re-trip the per-IP limit.
    """
    delay = base_delay * (attempt + 1)
    if _is_connection_limit_error(error):
        delay *= 4
    return delay + random.uniform(0, delay)


def connect_ftp(server, user, password):
    """
    Connect over FTPS (explicit TLS) when the server supports it, falling back
    to plain FTP so credentials are encrypted whenever possible.
    """
    global _ftps_supported

    if _ftps_supported is not False:
        ftps = None
        try:
            ftps = FTP_TLS(server, timeout=30)
            ftps.login(user, password)
            ftps.prot_p()  # Encrypt the data channel too
            _ftps_supported = True
            return ftps
        except (error_temp, socket.gaierror, TimeoutError, EOFError):
            # A busy server (421), a DNS failure, a timeout or a hangup says
            # nothing about TLS support. Retrying in plain FTP would fail the
            # same way while burning a second connection slot, so surface the
            # error instead. A hangup must not latch _ftps_supported to False
            # either: that would send the rest of the run's credentials in the
            # clear over one transient drop.
            close_ftp(ftps)
            raise
        except Exception as e:
            close_ftp(ftps)
            _ftps_supported = False
            logger.warning(f"FTPS unavailable ({e}), falling back to plain FTP")

    ftp = FTP(server, timeout=30)
    ftp.login(user, password)
    return ftp


class Webcam:
    # Shared FTP connections for all webcam instances. Subclasses assign through
    # `Webcam`, never `cls`/`self.__class__`: a subclass attribute would shadow
    # these and quietly open a second pool that main.py's _close_connections()
    # never releases.
    _download_ftp = None
    _upload_ftp = None
    _download_lock = threading.Lock()
    _upload_lock = threading.Lock()

    def __init__(
        self, name, file_name_on_server=None, logo_placements=None, blackout=False
    ):
        self.name = name
        self.file_buffer = io.BytesIO()
        self.file_name_on_server = file_name_on_server
        self.blackout = blackout

        # Process logo_placements (supports both single overlays and grouped overlays)
        overlay_list = logo_placements or []

        # Handle grouped overlays (list of lists/tuples)
        if overlay_list and isinstance(overlay_list[0], (list, tuple)):
            self.overlays = []
            for group in overlay_list:
                if len(group) == 1:
                    self.overlays.append(group[0])
                else:
                    self.overlays.append(CompositeOverlay(group))
        else:
            self.overlays = overlay_list

        self.mod_time = None
        self.mod_time_str = ""
        self.upload = []

    def _download_image(self, max_retries=3, retry_delay=2):
        """Download image using shared FTP connection with retry logic."""

        def download_attempt():
            # Hold the lock only while talking to the server so retry sleeps
            # don't stall the other cameras' downloads.
            logger.debug(f"  {self.name}: Waiting for download lock...")
            with self._download_lock:
                logger.debug(f"  {self.name}: Got download lock...")
                ftp = self._get_download_connection()
                ftp.retrbinary(
                    f"RETR {self.file_name_on_server}", self.file_buffer.write
                )
                self.file_buffer.seek(0)
                self._set_modification_time(ftp)

        # Try to download the image with connection retry logic
        for attempt in range(max_retries):
            try:
                download_attempt()
                logger.debug(f"  {self.name}: Download successful")
                return  # Success - exit retry loop

            except error_perm as e:
                if not str(e).startswith("550"):
                    raise

                # The upstream replaces each frame in place every half minute or
                # so, and the swap isn't atomic: a RETR that lands between the
                # delete and the new upload gets a 550 for a file that is there
                # the rest of the time. The gap is under a second, so spend the
                # budget on more attempts rather than one long wait: two rounds
                # plus main's ROUND_INTERVAL have to fit inside a cron minute.
                self.file_buffer = io.BytesIO()  # Discard any partial read
                if attempt < max_retries - 1:
                    logger.info(
                        f"  {self.name}: File not found, "
                        f"retrying in {retry_delay:.1f}s..."
                    )
                    sleep(retry_delay)
                else:
                    raise FileNotFoundError(
                        f"{self.name} wasn't found in the folder."
                    ) from e

            except RETRYABLE_FTP_ERRORS as e:
                # Retryable, unlike the 5xx error_perm handled above.
                logger.warning(
                    f"  {self.name}: Download failed (attempt {attempt + 1}): {e}"
                )
                # Reset connection on error, closing it so the server releases
                # its slot instead of holding the session until it times out.
                # Closed while holding the lock so the slot is given back before
                # another camera thread opens its replacement.
                with self._download_lock:
                    stale, Webcam._download_ftp = Webcam._download_ftp, None
                    close_ftp(stale)
                self.file_buffer = io.BytesIO()  # Reset buffer
                if attempt < max_retries - 1:
                    delay = retry_delay_for(retry_delay, attempt, e)
                    logger.info(f"  {self.name}: Retrying download in {delay:.1f}s...")
                    sleep(delay)
                else:
                    logger.error(
                        f"  {self.name}: Download failed after {max_retries} tries"
                    )
                    raise

    def _apply_blackout(self):
        """Replace the downloaded image with a black frame of the same size.

        Used to override a feed (e.g. when a camera has been bumped or aimed
        somewhere it shouldn't be). No overlays (including the logo) are applied
        in blackout mode, so every output feed is a bare black frame.
        """
        logger.info(f"  {self.name}: Blackout enabled, replacing with black frame")
        self.file_buffer.seek(0)
        with Image.open(self.file_buffer) as img:
            size = img.size
        black = Image.new("RGB", size, (0, 0, 0))
        self.file_buffer = io.BytesIO()
        black.save(self.file_buffer, format="JPEG")
        self.file_buffer.seek(0)

    def _apply_overlays(self):
        """Add all overlays to the image.

        In blackout mode the logo is skipped: each feed's output is just the
        black frame, but the per-feed filenames (via each overlay's subname)
        are preserved so the same set of images is published.
        """
        if self.blackout:
            logger.debug(f"  {self.name}: Blackout mode, skipping logo overlays")
            for overlay in self.overlays:
                self.file_buffer.seek(0)
                overlay.overlayed = io.BytesIO()
                overlay.overlayed.write(self.file_buffer.read())
                overlay.overlayed.seek(0)
            return

        logger.debug(f"  {self.name}: Applying {len(self.overlays)} overlays...")
        for i, overlay in enumerate(self.overlays):
            logger.debug(
                f"  {self.name}: Processing overlay {i + 1}/{len(self.overlays)}..."
            )
            overlay.add_overlay(self.file_buffer, self.mod_time_str)
        logger.debug(f"  {self.name}: Finished applying overlays")

    def upload_image(self, max_retries=3, retry_delay=2):
        """Upload processed images using shared FTP connection with retry logic."""
        self.upload = []
        with self._upload_lock:

            def upload_file(overlayed, file_name):
                for attempt in range(max_retries):
                    try:
                        ftp = self._get_upload_connection()
                        overlayed.seek(0)  # Reset buffer position

                        # Atomic file replacement: upload to temporary file first.
                        # PID in the name so overlapping cron runs don't rename
                        # each other's temp files out from under them.
                        temp_name = f"{file_name}.{os.getpid()}.tmp"
                        ftp.storbinary("STOR " + temp_name, overlayed)

                        try:
                            # Atomically rename to final name
                            ftp.rename(temp_name, file_name)
                        except Exception as rename_error:
                            # Clean up temp file if rename fails
                            try:
                                ftp.delete(temp_name)
                            except Exception:
                                pass  # Ignore cleanup errors
                            raise rename_error

                        self.upload += [f"https://glacier.org/webcam/{file_name}"]
                        return  # Success - exit retry loop
                    except RETRYABLE_FTP_ERRORS as e:
                        logger.warning(
                            f"  {self.name}: Upload failed for {file_name} "
                            f"(attempt {attempt + 1}): {e}"
                        )
                        # Reset connection on error, closing it so the server
                        # releases its slot instead of holding the session until
                        # it times out.
                        stale, Webcam._upload_ftp = Webcam._upload_ftp, None
                        close_ftp(stale)
                        if attempt < max_retries - 1:
                            delay = retry_delay_for(retry_delay, attempt, e)
                            logger.info(
                                f"  {self.name}: Retrying upload in {delay:.1f}s..."
                            )
                            sleep(delay)
                        else:
                            logger.error(
                                f"  {self.name}: Upload failed after {max_retries}x"
                            )
                            raise

            self._process_overlay_files(upload_file)

    def _record_mod_time(self, mod_time_utc: datetime):
        """Store when the source image was taken, in Mountain Time.

        Takes an aware UTC timestamp so any source can feed it — an FTP MDTM
        reply or an HTTP Last-Modified header.
        """
        mod_time = mod_time_utc.astimezone(ZoneInfo("America/Denver"))
        self.mod_time = mod_time
        # lstrip("0") drops the leading zero of the hour portably
        # (strftime's %-I is glibc/macOS-only)
        self.mod_time_str = (
            mod_time.strftime("%I:%M %p %b. %d, %Y")
            .lstrip("0")
            .replace("AM", "am")
            .replace("PM", "pm")
        )

    def _set_modification_time(self, ftp: FTP):
        # Send the MDTM command to the FTP server
        try:
            response = ftp.sendcmd(f"MDTM {self.file_name_on_server}")

            # The response will be in the format: '213 YYYYMMDDHHMMSS'
            if response.startswith("213"):
                time_str = response[4:].strip()
                self._record_mod_time(
                    datetime.strptime(time_str, "%Y%m%d%H%M%S").replace(
                        tzinfo=ZoneInfo("UTC")
                    )
                )

        except error_perm as e:
            # 550 errors can be ignored, but the image then goes out
            # with a blank timestamp
            if str(e).startswith("550"):
                logger.warning(
                    f"  {self.name}: Could not read modification time (550); "
                    "timestamp will be blank"
                )
            else:
                raise

    def _process_overlay_files(self, action_func):
        """Process each overlay file with the given action function."""
        for overlay in self.overlays:
            overlayed, file_name = overlay.get_overlayed_img(self.name)
            action_func(overlayed, file_name)

    def save_debug_images(self):
        """Save processed images to debug-images folder for debugging purposes."""
        debug_dir = resolve_path("debug-images")
        os.makedirs(debug_dir, exist_ok=True)

        def save_file(overlayed, file_name):
            debug_path = os.path.join(debug_dir, file_name)
            with open(debug_path, "wb") as f:
                f.write(overlayed.read())
            logger.info(f"Saved debug image: {debug_path}")

        self._process_overlay_files(save_file)

    def process(self, max_retries=3, retry_delay=1.5):
        """Download and process webcam image with overlays."""
        for attempt in range(max_retries):
            try:
                # Clear buffer from any previous attempts
                self.file_buffer = io.BytesIO()

                # Download and process image
                self._download_image()
                if self.blackout:
                    self._apply_blackout()
                self._apply_overlays()
                return  # Success - exit early

            except (OSError, UnidentifiedImageError) as e:
                # Check if it's a truncated image error or unidentified image
                if (
                    "image file is truncated" in str(e).lower()
                    or "broken data stream" in str(e).lower()
                    or "cannot identify image file" in str(e).lower()
                ):
                    if attempt < max_retries - 1:  # Not the last attempt
                        logger.info(
                            f"{self.name}: Corrupted/truncated image detected "
                            f"(attempt {attempt + 1}), retrying in {retry_delay}s..."
                        )
                        sleep(retry_delay)
                        continue
                    else:
                        logger.error(
                            f"{self.name}: Image still corrupted after "
                            f"{max_retries} attempts"
                        )
                        raise
                else:
                    # Different OSError, re-raise immediately
                    raise

    @classmethod
    def _get_download_connection(cls):
        """
        Get shared FTP connection for downloading images.
        Must be called with _download_lock held.
        """
        if cls._download_ftp is None:
            logger.debug("    Creating new download FTP connection...")
            try:
                Webcam._download_ftp = connect_ftp(
                    os.getenv("server"),
                    os.getenv("ftp_get_user"),
                    os.getenv("ftp_get_pwd"),
                )
                logger.debug("    Download FTP connection established")
            except Exception as e:
                logger.error(f"    Failed to create download connection: {e}")
                Webcam._download_ftp = None
                raise ConnectionError(
                    f"Failed to create download FTP connection: {e}"
                ) from e
        else:
            logger.debug("    Reusing existing download FTP connection")
        return Webcam._download_ftp

    @classmethod
    def _get_upload_connection(cls):
        """
        Get shared FTP connection for uploading images.
        Must be called with _upload_lock held.
        """
        if cls._upload_ftp is None:
            try:
                Webcam._upload_ftp = connect_ftp(
                    os.getenv("server"),
                    os.getenv("username"),
                    os.getenv("password"),
                )
            except Exception as e:
                Webcam._upload_ftp = None
                raise ConnectionError(
                    f"Failed to create upload FTP connection: {e}"
                ) from e
        return Webcam._upload_ftp

    @classmethod
    def _close_connections(cls):
        """Close all shared FTP connections."""
        with cls._download_lock:
            close_ftp(Webcam._download_ftp)
            Webcam._download_ftp = None

        with cls._upload_lock:
            close_ftp(Webcam._upload_ftp)
            Webcam._upload_ftp = None
