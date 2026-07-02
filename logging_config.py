"""
Logging configuration module for GNPC webcam system.
Handles environment-based logging setup for console or file output.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from paths import resolve_path


def setup_logging():
    """Configure logging based on environment variables."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_output = os.getenv("LOG_OUTPUT", "console").lower()
    log_file = os.getenv("LOG_FILE", "webcams.log")
    max_bytes = int(os.getenv("LOG_MAX_BYTES", 5 * 1024 * 1024))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", 3))

    if log_output == "file":
        handler = RotatingFileHandler(
            resolve_path(log_file), maxBytes=max_bytes, backupCount=backup_count
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logging.basicConfig(
            level=getattr(logging, log_level), handlers=[handler], force=True
        )
    else:
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            force=True,
        )
