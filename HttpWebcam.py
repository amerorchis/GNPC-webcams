"""
A webcam whose source image is served over HTTP(S) instead of the
glacier.org FTP server.
"""

import io
import logging
from email.utils import parsedate_to_datetime
from time import sleep

import requests

from Overlays import USER_AGENT
from Webcam import Webcam, retry_delay_for

logger = logging.getLogger(__name__)


class HttpWebcam(Webcam):
    """A webcam fetched from a URL.

    Only the download differs from `Webcam`: overlays, filenames and the upload
    back to glacier.org are inherited unchanged, so an HTTP-sourced camera is
    configured and published exactly like an FTP one.
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

    def _download_image(self, max_retries=3, retry_delay=2):
        """Fetch the source image over HTTP with retry logic."""
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    self.url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=self.timeout,
                )
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

            self.file_buffer = io.BytesIO(response.content)
            self._set_mod_time_from_header(response.headers.get("Last-Modified"))
            logger.debug(f"  {self.name}: Download successful")
            return

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
