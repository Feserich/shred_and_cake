"""Runtime configuration read from the environment."""

import os
import secrets
import sys
from pathlib import Path


def data_dir() -> Path:
    """Folder for database, journal and backups.

    In the packaged executable it lies next to the exe, so it does not depend on where the
    program was started from; otherwise it is ``data/`` in the working directory.
    """
    override = os.environ.get("SKIBASAR_DATA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path("data")


def admin_pin() -> str | None:
    """PIN that guards edits of settled sellers; ``None`` means such edits are disabled."""
    return os.environ.get("SKIBASAR_ADMIN_PIN") or None


def check_admin_pin(given: str) -> bool:
    expected = admin_pin()
    return expected is not None and secrets.compare_digest(given.strip(), expected)


def event_pin() -> str | None:
    """PIN that LAN clients (not localhost) must enter; ``None`` means no PIN is required."""
    return os.environ.get("SKIBASAR_EVENT_PIN") or None


def new_event_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"
