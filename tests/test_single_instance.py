"""Tests for the overlapping-run guard (no network)."""

import os
import subprocess
import sys

import pytest

from paths import BASE_DIR
from single_instance import AlreadyRunning, SingleInstance


@pytest.fixture
def lock_name(tmp_path):
    """An absolute lock path, so tests never touch the real webcams.lock."""
    return str(tmp_path / "test.lock")


def test_lock_is_acquired_when_free(lock_name):
    with SingleInstance(lock_name):
        assert os.path.exists(lock_name)


def test_second_run_is_refused_while_the_first_holds_the_lock(lock_name):
    """The whole point: a run that overlaps another must not open FTP sessions."""
    with SingleInstance(lock_name):
        with pytest.raises(AlreadyRunning):
            with SingleInstance(lock_name):
                raise AssertionError("second instance should not have acquired")


def test_lock_is_released_on_exit(lock_name):
    with SingleInstance(lock_name):
        pass

    with SingleInstance(lock_name):  # Must not raise
        pass


def test_lock_is_released_when_the_run_raises(lock_name):
    """A crashing run must not leave the lock wedged for every later run."""
    with pytest.raises(RuntimeError):
        with SingleInstance(lock_name):
            raise RuntimeError("processing blew up")

    with SingleInstance(lock_name):  # Must not raise
        pass


def test_refused_run_does_not_erase_the_holder_pid(lock_name):
    """The lock file names the process actually running, for debugging on the Pi."""
    with SingleInstance(lock_name):
        with pytest.raises(AlreadyRunning):
            with SingleInstance(lock_name):
                pass

        with open(lock_name) as f:
            assert f.read().strip() == str(os.getpid())


def test_lock_is_released_when_the_holder_is_killed(lock_name):
    """flock is held by the process, so a SIGKILLed run can't wedge the system."""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from single_instance import SingleInstance;"
            "lock = SingleInstance(sys.argv[2]).__enter__();"
            "print('locked', flush=True);"
            "sys.stdin.read()",
            str(BASE_DIR),
            lock_name,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"

        with pytest.raises(AlreadyRunning):
            with SingleInstance(lock_name):
                pass

        holder.kill()
        holder.wait(timeout=10)

        with SingleInstance(lock_name):  # Kernel released it with the process
            pass
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
        holder.stdout.close()
        holder.stdin.close()
