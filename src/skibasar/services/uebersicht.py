"""Overview tables (Übersicht): searchable lists and audited manual edits."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..fees import paid_at_entry_cents
from ..models import (
    Article,
    ArticleStatus,
    AuditLog,
    Event,
    Sale,
    Seller,
    SellerType,
)
from . import admin_pin as admin_pin_service
from . import audit

LIMIT = 500

_SELLER_TEXT = ("name", "first_name", "phone", "email", "address", "notes")
_ARTICLE_TEXT = ("description", "brand", "size", "color")
# "sold" is only reachable through the checkout, never by hand
_EDITABLE_STATUS = (ArticleStatus.available, ArticleStatus.returned, ArticleStatus.withdrawn)


class UebersichtError(ValueError):
    pass


def _require_pin(s: Session, pin: str) -> None:
    try:
        admin_pin_service.require(s, pin)
    except admin_pin_service.AdminPinError as e:
        raise UebersichtError(str(e)) from e


def list_sellers(s: Session, q: str = "", type_: str = "", status: str = "") -> list[Seller]:
    stmt = select(Seller).order_by(Seller.type, Seller.name, Seller.id)
    q = q.strip()
    if q:
        cond = [Seller.name.ilike(f"%{q}%"), Seller.first_name.ilike(f"%{q}%")]
        if q.isdigit():
            cond.append(Seller.id.in_(select(Article.seller_id).where(Article.number == int(q))))
        stmt = stmt.where(or_(*cond))
    if type_ in SellerType.__members__:
        stmt = stmt.where(Seller.type == SellerType(type_))
    if status == "offen":
        stmt = stmt.where(Seller.settled_at.is_(None))
    elif status == "abgerechnet":
        stmt = stmt.where(Seller.settled_at.is_not(None))
    return list(s.scalars(stmt.limit(LIMIT)))


def list_articles(s: Session, q: str = "", status: str = "") -> list[Article]:
    stmt = select(Article).join(Seller).order_by(Article.number)
    q = q.strip()
    if q:
        cond = [
            Article.description.ilike(f"%{q}%"),
            Article.brand.ilike(f"%{q}%"),
            Seller.name.ilike(f"%{q}%"),
            Seller.first_name.ilike(f"%{q}%"),
        ]
        if q.isdigit():
            cond.append(Article.number == int(q))
        stmt = stmt.where(or_(*cond))
    if status in ArticleStatus.__members__:
        stmt = stmt.where(Article.status == ArticleStatus(status))
    return list(s.scalars(stmt.limit(LIMIT)))


def list_sales(s: Session, status: str = "") -> list[Sale]:
    stmt = select(Sale).order_by(Sale.id.desc())
    if status == "gueltig":
        stmt = stmt.where(Sale.cancelled.is_(False))
    elif status == "storniert":
        stmt = stmt.where(Sale.cancelled.is_(True))
    return list(s.scalars(stmt.limit(LIMIT)))


def list_audit(s: Session, entity: str = "") -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    return list(s.scalars(stmt.limit(LIMIT)))


def update_seller(
    s: Session,
    seller: Seller,
    *,
    values: dict[str, str],
    fee_exempt: bool,
    offer_fee_paid_at_entry: bool,
    admin_pin_given: str = "",
    client: str = "",
) -> Seller:
    """Edit contact data and fee flags. Settled sellers: contact data only, and only with PIN."""
    new = {k: values.get(k, "").strip() for k in _SELLER_TEXT}
    if not new["name"]:
        raise UebersichtError("Name fehlt")
    if seller.settled_at is not None:
        _require_pin(s, admin_pin_given)
    else:
        new["fee_exempt"] = fee_exempt
        new["offer_fee_paid_at_entry"] = offer_fee_paid_at_entry and not fee_exempt
        new["offer_fee_paid_cents"] = paid_at_entry_cents(
            seller.offer_fee_paid_cents,
            paid=new["offer_fee_paid_at_entry"],
            fee_cents=s.get(Event, 1).offer_fee_cents(seller.type),
        )
    before = {k: getattr(seller, k) for k in new}
    if before == new:
        return seller
    for key, value in new.items():
        setattr(seller, key, value)
    audit.log(s, "seller", seller.id, "update", before, new, client)
    s.commit()
    return seller


def update_article(
    s: Session,
    article: Article,
    *,
    values: dict[str, str],
    price_cents: int,
    status: str,
    admin_pin_given: str = "",
    client: str = "",
) -> Article:
    """Edit an article. Sold articles keep price and status (use Storno at the checkout)."""
    new = {k: values.get(k, "").strip() for k in _ARTICLE_TEXT}
    if not new["description"]:
        raise UebersichtError("Artikelbezeichnung fehlt")
    if article.seller.settled_at is not None:
        _require_pin(s, admin_pin_given)
    if article.status == ArticleStatus.sold:
        if price_cents != article.price_cents:
            raise UebersichtError(
                "Der Preis eines verkauften Artikels kann nicht geändert werden – "
                "bitte zuerst den Verkauf stornieren"
            )
        if status != ArticleStatus.sold.value:
            raise UebersichtError(
                "Ein verkaufter Artikel wird über das Storno der Kasse wieder frei"
            )
    else:
        if price_cents <= 0:
            raise UebersichtError("Der Preis muss größer als 0 sein")
        if status not in {st.value for st in _EDITABLE_STATUS}:
            raise UebersichtError("Unbekannter Status")
        if article.seller.settled_at is not None and (
            price_cents != article.price_cents or status != article.status.value
        ):
            raise UebersichtError("Bei abgerechneten Verkäufern sind nur Texte änderbar")
        new["price_cents"] = price_cents
        new["status"] = status
    before = {k: getattr(article, k) for k in new}
    before = {k: (v.value if isinstance(v, ArticleStatus) else v) for k, v in before.items()}
    if before == new:
        return article
    for key, value in new.items():
        setattr(article, key, ArticleStatus(value) if key == "status" else value)
    audit.log(s, "article", article.id, "update", before, new, client)
    s.commit()
    return article
