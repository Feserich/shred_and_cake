"""Admin PIN: set it in the app (stored hashed) and require it for guarded actions."""

from sqlalchemy.orm import Session

from ..config import admin_pin, admin_pin_configured, check_admin_pin, hash_pin
from ..models import Event
from . import audit

MIN_LENGTH = 4


class AdminPinError(ValueError):
    pass


def require(s: Session, pin: str) -> None:
    stored = s.get(Event, 1).admin_pin_hash
    if not admin_pin_configured(stored):
        raise AdminPinError(
            "Dafür ist die Admin-PIN nötig – es ist noch keine eingerichtet "
            "(unter Einstellungen festlegen)"
        )
    if not check_admin_pin(pin, stored):
        raise AdminPinError("Die Admin-PIN ist falsch")


def set_pin(s: Session, *, current: str, new: str, client: str = "") -> None:
    """Set or change the PIN. An existing PIN must be given first. The PIN is never logged."""
    event = s.get(Event, 1)
    if admin_pin() is not None:
        raise AdminPinError("Die Admin-PIN ist über SKIBASAR_ADMIN_PIN festgelegt")
    had_pin = bool(event.admin_pin_hash)
    if had_pin:
        require(s, current)
    new = new.strip()
    if len(new) < MIN_LENGTH or not new.isdigit():
        raise AdminPinError(f"Die neue PIN muss aus mindestens {MIN_LENGTH} Ziffern bestehen")
    event.admin_pin_hash = hash_pin(new)
    audit.log(s, "event", 1, "admin_pin", {"set": had_pin}, {"set": True}, client)
    s.commit()
