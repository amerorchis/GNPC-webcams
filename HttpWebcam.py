"""
A webcam whose source image is served over HTTP(S) instead of the
glacier.org FTP server.
"""

import io
import json
import logging
import os
import tempfile
from email.utils import parsedate_to_datetime
from time import sleep

import requests
from PIL import Image, UnidentifiedImageError

from Overlays import USER_AGENT
from Webcam import Webcam, retry_delay_for

logger = logging.getLogger(__name__)


class HttpWebcam(Webcam):
    """A webcam fetched from a URL.

    Only the download differs from `Webcam`: overlays, filenames and the upload
    back to glacier.org are inherited unchanged, so an HTTP-sourced camera is
    configured and published exactly like an FTP one.

    The fetch is conditional. The validators (`ETag`, `Last-Modified`) of the
    frame most recently *published* are kept on disk between cron runs and sent
    back as `If-None-Match` / `If-Modified-Since`; a 304 means the source still
    shows what glacier.org already has, so the run skips the overlay and upload
    for this camera. Some of these sources refresh every few minutes, one of
    them every few hours, and the pipeline polls twice a minute.

    A 200 whose body is not an image (nps.gov has served a zero-byte file for
    hours at a time) is not an error to report: the frame already on
    glacier.org stays up, and the response's validators are recorded so the
    bad object answers 304 until the source replaces it.
    """

    def __init__(self, name, url, logo_placements=None, blackout=False, timeout=20):
        super().__init__(
            name,
            file_name_on_server=None,
            logo_placements=logo_placements,
            blackout=blackout,
        )
        self.url = url
        self.timeout = timeout
        # Validators of the frame currently in file_buffer, promoted to the
        # on-disk record once that frame has been uploaded.
        self._pending_validators = None

    def _download_image(self, max_retries=3, retry_delay=2):
        """Fetch the source image over HTTP with retry logic."""
        self.source_unchanged = False
        self._pending_validators = None
        headers = {"User-Agent": USER_AGENT, **self._conditional_headers()}

        for attempt in range(max_retries):
            try:
                response = requests.get(self.url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
            except requests.RequestException as e:
                logger.warning(
                    f"  {self.name}: Download failed (attempt {attempt + 1}): {e}"
                )
                if attempt < max_retries - 1:
                    delay = retry_delay_for(retry_delay, attempt, e)
                    logger.info(f"  {self.name}: Retrying download in {delay:.1f}s...")
                    sleep(delay)
                    continue
                logger.error(
                    f"  {self.name}: Download failed after {max_retries} tries"
                )
                raise

            if response.status_code == 304:
                logger.debug(f"  {self.name}: Not modified since last publish")
                self.source_unchanged = True
                return

            validators = {
                "url": self.url,
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }
            frame = io.BytesIO(response.content)
            if not self._is_image(frame):
                logger.warning(
                    f"  {self.name}: Source served {len(response.content)} bytes "
                    f"of {response.headers.get('Content-Type')!r} that is not an "
                    "image; keeping the published frame until the source changes"
                )
                self._write_validators(validators)
                self.source_unchanged = True
                return

            self.file_buffer = frame
            self._set_mod_time_from_header(response.headers.get("Last-Modified"))
            self._pending_validators = validators
            logger.debug(f"  {self.name}: Download successful")
            return

    @staticmethod
    def _is_image(buffer):
        """Whether Pillow recognises the buffer's header as an image.

        Only the header is read; a frame truncated further in still goes on
        to `process()`, whose retry handles that case.
        """
        try:
            with Image.open(buffer):
                pass
        except UnidentifiedImageError:
            return False
        finally:
            buffer.seek(0)
        return True

    def upload_image(self, max_retries=3, retry_delay=2):
        """Upload as `Webcam` does, then remember which frame was published.

        The validators are recorded only after a successful upload: a frame
        that was fetched but never made it to glacier.org must be fetched
        again next run, not skipped as already seen.
        """
        super().upload_image(max_retries=max_retries, retry_delay=retry_delay)
        if self._pending_validators and not self.source_unchanged:
            self._write_validators(self._pending_validators)

    # -- conditional-request bookkeeping -------------------------------------

    def _validators_path(self):
        return os.path.join(tempfile.gettempdir(), f"gnpc-http-{self.name}.json")

    def _read_validators(self):
        """The validators of the last frame published or rejected, or None.

        Ignored if recorded against a different URL, so re-pointing a camera in
        the config can never make its first fetch look "not modified".
        """
        try:
            with open(self._validators_path(), "r") as f:
                validators = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(validators, dict) or validators.get("url") != self.url:
            return None
        return validators

    def _conditional_headers(self):
        validators = self._read_validators()
        if not validators:
            return {}
        headers = {}
        if validators.get("etag"):
            headers["If-None-Match"] = validators["etag"]
        if validators.get("last_modified"):
            headers["If-Modified-Since"] = validators["last_modified"]
        return headers

    def _write_validators(self, validators):
        if not (validators.get("etag") or validators.get("last_modified")):
            # Nothing a server could match against; leave no record rather
            # than an empty one.
            return
        path = self._validators_path()
        # Unique temp name so overlapping runs can't read a half-written file.
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w") as f:
                json.dump(validators, f)
            os.replace(temp_path, path)
        except OSError as e:
            logger.warning(f"  {self.name}: Could not record validators: {e}")
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _set_mod_time_from_header(self, last_modified):
        """Record when the source image was taken, from the Last-Modified header.

        Without the header the image goes out with a blank timestamp, matching
        what the FTP path does when MDTM is unavailable.
        """
        if not last_modified:
            logger.warning(
                f"  {self.name}: No Last-Modified header; timestamp will be blank"
            )
            return

        try:
            self._record_mod_time(parsedate_to_datetime(last_modified))
        except (TypeError, ValueError) as e:
            logger.warning(
                f"  {self.name}: Could not parse Last-Modified "
                f"{last_modified!r} ({e}); timestamp will be blank"
            )
