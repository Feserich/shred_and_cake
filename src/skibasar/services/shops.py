"""Shop management, event settings and the article import (preview diff + commit)."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..csv_import import ImportRow, ParsedCsv
from ..fees import paid_at_entry_cents
from ..models import Article, ArticleStatus, Event, Seller, SellerType
from . import audit
from .numbering import RangeError, validate_shop_range

SETTLED_IMPORT_MESSAGE = (
    "Dieser Händler ist bereits abgerechnet – ein Import ist nicht mehr möglich."
)


def update_event(s: Session, values: dict, client: str = "") -> Event:
    event = s.get(Event, 1)
    before = {k: getattr(event, k) for k in values}
    for key, value in values.items():
        setattr(event, key, value)
    audit.log(s, "event", 1, "update", before, values, client)
    s.commit()
    return event


def list_shops(s: Session) -> list[Seller]:
    return list(
        s.scalars(
            select(Seller).where(Seller.type == SellerType.shop).order_by(Seller.number_range_start)
        )
    )


def save_shop(
    s: Session,
    shop: Seller | None,
    *,
    name: str,
    range_start: int,
    range_end: int,
    fee_exempt: bool = False,
    offer_fee_paid_at_entry: bool = False,
    phone: str = "",
    email: str = "",
    notes: str = "",
    client: str = "",
) -> Seller:
    name = name.strip()
    if not name:
        raise RangeError("Name fehlt")
    validate_shop_range(s, range_start, range_end, exclude_seller_id=shop.id if shop else None)
    paid = offer_fee_paid_at_entry and not fee_exempt
    values = {
        "name": name,
        "number_range_start": range_start,
        "number_range_end": range_end,
        "fee_exempt": fee_exempt,
        "offer_fee_paid_at_entry": paid,
        "offer_fee_paid_cents": paid_at_entry_cents(
            shop.offer_fee_paid_cents if shop else None,
            paid=paid,
            fee_cents=s.get(Event, 1).offer_fee_shop_cents,
        ),
        "phone": phone.strip(),
        "email": email.strip(),
        "notes": notes.strip(),
    }
    if shop is None:
        shop = Seller(type=SellerType.shop, **values)
        s.add(shop)
        s.flush()
        audit.log(s, "seller", shop.id, "create", None, values, client)
    else:
        outside = [a.number for a in shop.articles if not range_start <= a.number <= range_end]
        if outside:
            raise RangeError(f"Artikel {outside[0]} läge außerhalb des neuen Bereichs")
        before = {k: getattr(shop, k) for k in values}
        for key, value in values.items():
            setattr(shop, key, value)
        audit.log(s, "seller", shop.id, "update", before, values, client)
    s.commit()
    return shop


@dataclass
class ImportDiff:
    new: list[ImportRow] = field(default_factory=list)
    changed: list[ImportRow] = field(default_factory=list)
    unchanged: list[ImportRow] = field(default_factory=list)
    removed: list[Article] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_COMPARED = ("shop_ref", "description", "brand", "size", "color", "price_cents")


def _differs(article: Article, row: ImportRow) -> bool:
    return any(getattr(article, k) != getattr(row, k) for k in _COMPARED)


def _existing(s: Session, shop: Seller) -> dict[int, Article]:
    q = select(Article).where(Article.seller_id == shop.id)
    return {a.number: a for a in s.scalars(q)}


def diff_import(s: Session, shop: Seller, parsed: ParsedCsv) -> ImportDiff:
    """Compare parsed rows with the shop's existing articles (re-import = replace)."""
    diff = ImportDiff()
    existing = _existing(s, shop)
    in_file = {r.number for r in parsed.rows if r.number is not None}
    taken = set(
        s.scalars(
            select(Article.number).where(Article.seller_id != shop.id, Article.number.in_(in_file))
        )
    )
    for row in parsed.rows:
        if row.number in taken:
            row.errors.append(f"Nummer {row.number} gehört bereits einem anderen Verkäufer")
            continue
        article = existing.get(row.number)
        if article is None:
            diff.new.append(row)
        elif _differs(article, row):
            diff.changed.append(row)
            if article.status != ArticleStatus.available:
                diff.errors.append(f"Artikel {article.number} ist bereits {article.status.value}")
        else:
            diff.unchanged.append(row)
    for number, article in existing.items():
        if number not in in_file:
            diff.removed.append(article)
            if article.status != ArticleStatus.available:
                diff.errors.append(f"Artikel {number} ist bereits {article.status.value}")
    return diff


def apply_import(s: Session, shop: Seller, parsed: ParsedCsv, client: str = "") -> ImportDiff:
    """Commit the import in one transaction. Refuses if the preview had any error."""
    if shop.settled_at is not None:
        raise RangeError(SETTLED_IMPORT_MESSAGE)
    diff = diff_import(s, shop, parsed)
    if parsed.has_errors or diff.errors:
        raise RangeError("Der Import enthält Fehler und kann nicht übernommen werden")
    existing = _existing(s, shop)
    for row in diff.new:
        s.add(
            Article(
                seller_id=shop.id,
                number=row.number,
                **{k: getattr(row, k) for k in _COMPARED},
            )
        )
    for row in diff.changed:
        for k in _COMPARED:
            setattr(existing[row.number], k, getattr(row, k))
    for article in diff.removed:
        s.delete(article)
    audit.log(
        s,
        "seller",
        shop.id,
        "import",
        None,
        {
            "new": len(diff.new),
            "changed": len(diff.changed),
            "removed": len(diff.removed),
            "total_cents": parsed.computed_total,
        },
        client,
    )
    s.commit()
    return diff
