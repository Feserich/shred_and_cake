"""Delete all Basar data (e.g. test data before the real Basar); settings and admin PIN stay.

The mail account stays as well; the mail queue goes (it holds sellers' data).
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import admin_pin_configured
from ..models import (
    Article,
    AuditLog,
    Closing,
    Event,
    Expense,
    OutgoingMail,
    Sale,
    SaleItem,
    Seller,
)
from . import admin_pin, audit

CONFIRM_WORD = "LÖSCHEN"

# Children before parents (foreign keys are enforced)
TABLES = (OutgoingMail, SaleItem, Article, Sale, Seller, Expense, Closing, AuditLog)


class ResetError(ValueError):
    pass


def check(s: Session, *, confirm: str, pin: str = "") -> None:
    """Require the confirmation word and, if one is configured, the admin PIN."""
    if confirm.strip().upper() != CONFIRM_WORD:
        raise ResetError(f"Zur Bestätigung bitte „{CONFIRM_WORD}“ eingeben")
    if admin_pin_configured(s.get(Event, 1).admin_pin_hash):
        try:
            admin_pin.require(s, pin)
        except admin_pin.AdminPinError as e:
            raise ResetError(str(e)) from e


def delete_all_data(s: Session, *, client: str = "") -> dict:
    """Delete sellers, shops, articles, sales, expenses, closing values, mails and the audit log.

    Call ``check`` first. Returns the number of deleted sellers, articles and sales.
    """
    counts = {
        "sellers": s.scalar(select(func.count()).select_from(Seller)),
        "articles": s.scalar(select(func.count()).select_from(Article)),
        "sales": s.scalar(select(func.count()).select_from(Sale)),
    }
    for table in TABLES:
        s.execute(delete(table))
    # The only entry left in the (new) protocol records the deletion itself
    audit.log(s, "event", 1, "delete_all_data", counts, None, client)
    s.commit()
    return counts
