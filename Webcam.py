"""
Custom class to represent an individual webcam.
"""

import io
import os
import logging
import threading
from time import sleep
from ftplib import FTP, error_perm
from datetime import datetime, timedelta
from dotenv import load_dotenv
from Overlays import CompositeOverlay

logger = logging.getLogger(__name__)

load_dotenv('environment.env')

class Webcam:
    # Shared FTP connections for all webcam instances
    _download_ftp = None
    _upload_ftp = None
    _download_lock = threading.Lock()
    _upload_lock = threading.Lock()
    
    def __init__(self, name, file_name_on_server, logo_placements=None):
        self.name = name
        self.file_buffer = io.BytesIO()
        self.file_name_on_server = file_name_on_server
        
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
        self.mod_time_str = ''
        self.upload = []

    def _download_image(self):
        """Download image using shared FTP connection."""
        logger.debug(f"  {self.name}: Waiting for download lock...")
        with self._download_lock:
            logger.debug(f"  {self.name}: Got download lock, getting FTP connection...")
            ftp = self._get_download_connection()
            logger.debug(f"  {self.name}: Got FTP connection, starting download...")
            
            def download_attempt():
                ftp.retrbinary(f'RETR {self.file_name_on_server}', self.file_buffer.write)
                self.file_buffer.seek(0)
                self._set_modification_time(ftp)

            # Try to download the image
            try:
                download_attempt()
                logger.debug(f"  {self.name}: Download successful")
            # If it's not there, wait 6 seconds and try again
            except error_perm as e:
                if str(e).startswith('550'):
                    logger.info(f"  {self.name}: File not found, waiting 6 seconds...")
                    sleep(6)
                    try:
                        download_attempt()
                        logger.debug(f"  {self.name}: Download successful on retry")
                    # If it's still not there, raise an exception
                    except error_perm as exc:
                        raise FileNotFoundError(f"{self.name} wasn't found in the folder.") from exc
                else:
                    raise

    def _apply_overlays(self):
        """Add all overlays to the image."""
        logger.debug(f"  {self.name}: Applying {len(self.overlays)} overlays...")
        for i, overlay in enumerate(self.overlays):
            logger.debug(f"  {self.name}: Processing overlay {i+1}/{len(self.overlays)}...")
            overlay.add_overlay(self.file_buffer, self.mod_time_str)
        logger.debug(f"  {self.name}: Finished applying overlays")
    

    def upload_image(self):
        """Upload processed images using shared FTP connection."""
        with self._upload_lock:
            ftp = self._get_upload_connection()
            
            def upload_file(overlayed, file_name):
                ftp.storbinary('STOR ' + file_name, overlayed)
                self.upload += [f'https://glacier.org/webcam/{file_name}']
            
            self._process_overlay_files(upload_file)

    def _set_modification_time(self, ftp: FTP):
        # Send the MDTM command to the FTP server
        try:
            response = ftp.sendcmd(f"MDTM {self.file_name_on_server}")

            # The response will be in the format: '213 YYYYMMDDHHMMSS'
            if response.startswith('213'):
                time_str = response[4:].strip()
                mod_time = datetime.strptime(time_str, '%Y%m%d%H%M%S') - timedelta(hours=6)
                self.mod_time = mod_time
                self.mod_time_str = mod_time.strftime('%-I:%M%p %b. %d, %Y')

        # 550 errors can be ignored
        except error_perm as e:
            if str(e).startswith('550'):
                pass

    def _process_overlay_files(self, action_func):
        """Process each overlay file with the given action function."""
        for overlay in self.overlays:
            overlayed, file_name = overlay.get_overlayed_img(self.name)
            action_func(overlayed, file_name)
    
    def save_debug_images(self):
        """Save processed images to debug-images folder for debugging purposes."""
        os.makedirs('debug-images', exist_ok=True)
        
        def save_file(overlayed, file_name):
            debug_path = os.path.join('debug-images', file_name)
            with open(debug_path, 'wb') as f:
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
                self._apply_overlays()
                return  # Success - exit early

            except OSError as e:
                # Check if it's a truncated image error
                if "image file is truncated" in str(e).lower() or "broken data stream" in str(e).lower():
                    if attempt < max_retries - 1:  # Not the last attempt
                        logger.info(f"{self.name}: Truncated image detected (attempt {attempt + 1}), retrying in {retry_delay}s...")
                        sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"{self.name}: Image still truncated after {max_retries} attempts")
                        raise
                else:
                    # Different OSError, re-raise immediately
                    raise

    @classmethod
    def _get_download_connection(cls):
        """Get shared FTP connection for downloading images. Must be called with _download_lock held."""
        if cls._download_ftp is None:
            logger.debug("    Creating new download FTP connection...")
            try:
                cls._download_ftp = FTP(os.getenv('server'))
                logger.debug("    Connected to server, logging in...")
                cls._download_ftp.login(os.getenv('ftp_get_user'), os.getenv('ftp_get_pwd'))
                logger.debug("    Download FTP connection established")
            except Exception as e:
                logger.error(f"    Failed to create download connection: {e}")
                cls._download_ftp = None
                raise ConnectionError(f"Failed to create download FTP connection: {e}") from e
        else:
            logger.debug("    Reusing existing download FTP connection")
        return cls._download_ftp

    @classmethod
    def _get_upload_connection(cls):
        """Get shared FTP connection for uploading images. Must be called with _upload_lock held."""
        if cls._upload_ftp is None:
            try:
                cls._upload_ftp = FTP(os.getenv('server'))
                cls._upload_ftp.login(os.getenv('username'), os.getenv('password'))
            except Exception as e:
                cls._upload_ftp = None
                raise ConnectionError(f"Failed to create upload FTP connection: {e}") from e
        return cls._upload_ftp

    @classmethod
    def _close_connections(cls):
        """Close all shared FTP connections."""
        with cls._download_lock:
            if cls._download_ftp:
                try:
                    cls._download_ftp.quit()
                except:
                    pass
                cls._download_ftp = None
        
        with cls._upload_lock:
            if cls._upload_ftp:
                try:
                    cls._upload_ftp.quit()
                except:
                    pass
                cls._upload_ftp = None