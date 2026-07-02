"""Unit tests for logging setup and rotation configuration."""

import logging
from logging.handlers import RotatingFileHandler

from logging_config import setup_logging


def _teardown_root_handlers():
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)


def test_file_output_uses_rotating_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_OUTPUT", "file")
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "test.log"))
    monkeypatch.setenv("LOG_MAX_BYTES", "1000")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "2")

    setup_logging()
    try:
        handlers = [
            h for h in logging.root.handlers if isinstance(h, RotatingFileHandler)
        ]
        assert len(handlers) == 1
        assert handlers[0].maxBytes == 1000
        assert handlers[0].backupCount == 2
    finally:
        _teardown_root_handlers()


def test_rotation_caps_log_size(monkeypatch, tmp_path):
    log_file = tmp_path / "rotate.log"
    monkeypatch.setenv("LOG_OUTPUT", "file")
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.setenv("LOG_MAX_BYTES", "500")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "2")

    setup_logging()
    try:
        logger = logging.getLogger("rotation-test")
        for i in range(100):
            logger.info("filler line %d to push the file over the size limit", i)

        assert log_file.stat().st_size <= 500
        assert (tmp_path / "rotate.log.1").exists()
    finally:
        _teardown_root_handlers()
