"""
Guard against overlapping runs.

Cron starts a run every minute, but a run that hits slow FTP transfers or a
retry backoff can outlast its minute. Each concurrent process opens its own FTP
sessions, and the server caps connections per IP, so stacked runs turn a slow
minute into "421 Too many connections" for every camera. Only one run at a time
is useful anyway: the next cron tick picks up whatever this one skipped.
"""

import fcntl
import logging
import os

from paths import resolve_path

logger = logging.getLogger(__name__)

LOCK_FILE = "webcams.lock"


class AlreadyRunning(Exception):
    """Raised when another run already holds the lock."""


class SingleInstance:
    """Hold an exclusive lock for the lifetime of a run.

    Uses flock, so the kernel releases the lock if the process is killed or dies
    without unwinding — a stale lock file can never wedge the system.
    """

    def __init__(self, lock_file=LOCK_FILE):
        self.lock_path = resolve_path(lock_file)
        self._fd = None

    def __enter__(self):
        # Opened without O_TRUNC so a running process's PID isn't blanked by a
        # later run that fails to get the lock.
        self._fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(self._fd)
            self._fd = None
            raise AlreadyRunning(
                f"another run holds {self.lock_path}; skipping this cycle"
            ) from e

        os.ftruncate(self._fd, 0)
        os.write(self._fd, f"{os.getpid()}\n".encode())
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._fd is not None:
            # Closing drops the flock. The file itself is left in place;
            # unlinking it would let a waiting run lock a path that has already
            # been replaced.
            os.close(self._fd)
            self._fd = None
        return False
