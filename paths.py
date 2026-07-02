"""
Anchors file access to the repository directory so the application behaves
the same regardless of the working directory it is launched from (e.g. cron).
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def resolve_path(path):
    """Return an absolute path, resolving relative paths against the repo directory."""
    p = Path(path)
    return str(p if p.is_absolute() else BASE_DIR / p)
