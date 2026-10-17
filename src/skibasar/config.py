"""Runtime configuration read from the environment."""

import hashlib
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
    """Admin PIN from the environment; it overrides the PIN stored in the database."""
    return os.environ.get("SKIBASAR_ADMIN_PIN") or None


def hash_pin(pin: str) -> str:
    """Salted scrypt hash as ``salt$hash`` (hex), for storing the PIN in the database."""
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}${hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1).hex()}"


def _matches_hash(given: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.scrypt(given.encode(), salt=salt, n=2**14, r=8, p=1)
    return secrets.compare_digest(actual, expected)


def admin_pin_configured(stored_hash: str | None) -> bool:
    return admin_pin() is not None or bool(stored_hash)


def check_admin_pin(given: str, stored_hash: str | None = None) -> bool:
    """Check against the environment PIN if set, otherwise against the stored hash."""
    given = given.strip()
    env = admin_pin()
    if env is not None:
        return secrets.compare_digest(given.encode(), env.encode())
    return bool(stored_hash) and _matches_hash(given, stored_hash)


def event_pin() -> str | None:
    """PIN that LAN clients (not localhost) must enter; ``None`` means no PIN is required."""
    return os.environ.get("SKIBASAR_EVENT_PIN") or None


def new_event_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"
