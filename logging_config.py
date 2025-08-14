"""
Logging configuration module for GNPC webcam system.
Handles environment-based logging setup for console or file output.
"""

import logging
import os


def setup_logging():
    """Configure logging based on environment variables."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_output = os.getenv("LOG_OUTPUT", "console").lower()
    log_file = os.getenv("LOG_FILE", "webcams.log")

    if log_output == "file":
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            filename=log_file,
            filemode="a",
        )
    else:
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
