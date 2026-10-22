"""Entry (Annahme): private seller registration and article entry with auto numbering."""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..fees import paid_at_entry_cents, paid_units_at_entry
from ..models import Article, ArticleStatus, Event, Seller, SellerType
from ..money import format_eur
from . import audit
from .numbering import next_private_number


class AnnahmeError(ValueError):
    pass


_SELLER_FIELDS = ("name", "first_name", "phone", "email", "address", "notes")


def search_private_sellers(s: Session, query: str = "") -> list[Seller]:
    """Private sellers by (first) name or by one of their article numbers; all if no query."""
    q = select(Seller).where(Seller.type == SellerType.private).order_by(Seller.name, Seller.id)
    query = query.strip()
    if query:
        conditions = [Seller.name.ilike(f"%{query}%"), Seller.first_name.ilike(f"%{query}%")]
        if query.isdigit():
            conditions.append(
                Seller.id.in_(select(Article.seller_id).where(Article.number == int(query)))
            )
        q = q.where(or_(*conditions))
    return list(s.scalars(q))


def save_private_seller(
    s: Session,
    seller: Seller | None,
    *,
    name: str,
    first_name: str = "",
    phone: str = "",
    email: str = "",
    address: str = "",
    notes: str = "",
    fee_exempt: bool = False,
    client: str = "",
) -> Seller:
    """Create or edit a private seller. The fee payment is recorded by ``collect_fee`` only."""
    if not name.strip():
        raise AnnahmeError("Name fehlt")
    if seller is not None and seller.settled_at is not None:
        raise AnnahmeError("Der Verkäufer ist bereits abgerechnet")
    texts = {"name": name, "first_name": first_name, "phone": phone, "email": email}
    texts |= {"address": address, "notes": notes}
    values = {k: texts[k].strip() for k in _SELLER_FIELDS}
    values["fee_exempt"] = fee_exempt
    values["offer_fee_paid_at_entry"] = bool(seller and seller.offer_fee_paid_at_entry) and (
        not fee_exempt
    )
    values["offer_fee_paid_units"] = paid_units_at_entry(
        seller.offer_fee_paid_units if seller else None,
        was_paid=bool(seller and seller.offer_fee_paid_at_entry),
        paid=values["offer_fee_paid_at_entry"],
        current_units=len(seller.articles) if seller else 0,
    )
    values["offer_fee_paid_cents"] = paid_at_entry_cents(
        seller.offer_fee_paid_cents if seller else None,
        paid=values["offer_fee_paid_at_entry"],
        fee_cents=s.get(Event, 1).offer_fee_private_cents,
    )
    if seller is None:
        seller = Seller(type=SellerType.private, **values)
        s.add(seller)
        s.flush()
        audit.log(s, "seller", seller.id, "create", None, values, client)
    else:
        before = {k: getattr(seller, k) for k in values}
        for key, value in values.items():
            setattr(seller, key, value)
        audit.log(s, "seller", seller.id, "update", before, values, client)
    s.commit()
    return seller


def collect_fee(s: Session, seller: Seller, client: str = "") -> int:
    """The seller pays the offer fee for all articles entered so far; returns the cash amount."""
    if seller.type != SellerType.private:
        raise AnnahmeError("Die Gebühr der Händler wird in den Händlerdaten verwaltet")
    if seller.settled_at is not None:
        raise AnnahmeError("Der Verkäufer ist bereits abgerechnet")
    if seller.fee_exempt:
        raise AnnahmeError("Dieser Verkäufer zahlt keine Angebotsgebühr")
    units = seller.fee_units_open
    if units == 0:
        raise AnnahmeError("Es ist nichts zu bezahlen")
    fee = s.get(Event, 1).offer_fee_private_cents
    before = {
        "paid": seller.offer_fee_paid_at_entry,
        "paid_cents": seller.offer_fee_paid_cents,
        "paid_units": seller.offer_fee_paid_units,
    }
    seller.offer_fee_paid_at_entry = True
    seller.offer_fee_paid_cents = (
        fee if seller.offer_fee_paid_cents is None else (seller.offer_fee_paid_cents)
    )
    seller.offer_fee_paid_units = seller.fee_units
    after = {
        "paid": True,
        "paid_cents": seller.offer_fee_paid_cents,
        "paid_units": seller.offer_fee_paid_units,
    }
    audit.log(s, "seller", seller.id, "collect_fee", before, after, client)
    s.commit()
    return fee * units


def add_article(
    s: Session,
    seller: Seller,
    *,
    expected_number: int | None,
    description: str,
    price_cents: int,
    brand: str = "",
    size: str = "",
    color: str = "",
    client: str = "",
) -> Article:
    """Create an article with the next free private number.

    ``expected_number`` is the number the volunteer saw on screen (and stuck on the tag). If
    another device took it in the meantime we refuse rather than silently hand out another one.
    """
    if seller.type != SellerType.private:
        raise AnnahmeError("Artikel von Händlern kommen über den CSV-Import")
    if seller.settled_at is not None:
        raise AnnahmeError("Der Verkäufer ist bereits abgerechnet")
    if not description.strip():
        raise AnnahmeError("Artikelbezeichnung fehlt")
    if price_cents <= 0:
        raise AnnahmeError("Der Preis muss größer als 0 sein")
    number = next_private_number(s)
    if expected_number is not None and expected_number != number:
        raise AnnahmeError(
            f"Nummer {expected_number} wurde inzwischen vergeben – die nächste Nummer ist {number}"
        )
    article = Article(
        number=number,
        seller_id=seller.id,
        description=description.strip(),
        brand=brand.strip(),
        size=size.strip(),
        color=color.strip(),
        price_cents=price_cents,
    )
    s.add(article)
    try:
        s.flush()
    except IntegrityError as e:  # another request won the race for this number
        s.rollback()
        raise AnnahmeError("Nummer wurde gerade vergeben – bitte erneut versuchen") from e
    audit.log(
        s,
        "article",
        article.id,
        "create",
        None,
        {"number": number, "seller_id": seller.id, "price_cents": price_cents},
        client,
    )
    s.commit()
    return article


def last_undoable_article(s: Session, seller: Seller) -> Article | None:
    """The seller's newest article, if it is also the newest private number and still unsold."""
    if seller.settled_at is not None or not seller.articles:
        return None
    last = max(seller.articles, key=lambda a: a.number)
    highest = s.scalar(
        select(func.max(Article.number)).join(Seller).where(Seller.type == SellerType.private)
    )
    if last.number != highest or last.status != ArticleStatus.available:
        return None
    return last


def undo_last_article(s: Session, seller: Seller, client: str = "") -> Article:
    """Remove the article just entered (typo), freeing its number again."""
    article = last_undoable_article(s, seller)
    if article is None:
        raise AnnahmeError("Der letzte Artikel kann nicht mehr zurückgenommen werden")
    before = {"number": article.number, "description": article.description}
    before["price_cents"] = article.price_cents
    audit.log(s, "article", article.id, "delete", before, None, client)
    s.delete(article)
    s.commit()
    return article


def suggestions(s: Session, column: str) -> list[str]:
    """Distinct earlier values of brand/size/color for the entry form autocomplete."""
    col = {"brand": Article.brand, "size": Article.size, "color": Article.color}[column]
    q = select(col).where(col != "").group_by(col).order_by(func.count().desc(), col).limit(50)
    return list(s.scalars(q))


def fee_status(event: Event, seller: Seller) -> str:
    """Human readable (German) offer fee status for screens and the printed list."""
    if seller.fee_exempt:
        return "Keine Angebotsgebühr (Provision wird berechnet)"
    fee = event.offer_fee_cents(seller.type)
    open_text = (
        f"{format_eur(fee * seller.fee_units_open)} offen (wird bei der Abrechnung abgezogen)"
    )
    if seller.offer_fee_paid_at_entry:
        paid = format_eur((seller.offer_fee_paid_cents or 0) * seller.fee_units_paid)
        if seller.fee_units_open:
            return f"Angebotsgebühr {paid} bezahlt, weitere {open_text}"
        return f"Angebotsgebühr {paid} bezahlt"
    return f"Angebotsgebühr {open_text}"
