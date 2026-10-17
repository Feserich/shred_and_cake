"""Pickup and settlement (Abholung): read-only preview first, one explicit commit afterwards."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session

from ..fees import FeeRules, Settlement, settle
from ..models import Article, ArticleStatus, Event, Seller, SellerType
from ..money import format_eur
from . import audit


class AbholungError(ValueError):
    pass


@dataclass(frozen=True)
class Preview:
    seller: Seller
    sold: list[Article]
    unsold: list[Article]  # still available: ticked as returned by default
    other: list[Article]  # already returned or withdrawn
    settlement: Settlement


def search_sellers(s: Session, query: str = "") -> list[Seller]:
    """Sellers of both types by name, article number or (shops) number range; all if no query."""
    q = select(Seller).order_by(Seller.type, Seller.name, Seller.id)
    query = query.strip()
    if query:
        conditions = [Seller.name.ilike(f"%{query}%"), Seller.first_name.ilike(f"%{query}%")]
        if query.isdigit():
            n = int(query)
            conditions.append(Seller.id.in_(select(Article.seller_id).where(Article.number == n)))
            conditions.append(and_(Seller.number_range_start <= n, Seller.number_range_end >= n))
        q = q.where(or_(*conditions))
    return list(s.scalars(q))


def rules_for(event: Event, seller: Seller) -> FeeRules:
    if seller.type == SellerType.shop:
        return FeeRules(event.offer_fee_shop_cents, event.commission_shop_bp)
    return FeeRules(event.offer_fee_private_cents, event.commission_private_bp)


def preview(s: Session, seller: Seller) -> Preview:
    """Everything the settlement screen and invoice show. Never writes."""
    event = s.get(Event, 1)
    by_status = {st: [] for st in ArticleStatus}
    for a in seller.articles:
        by_status[a.status].append(a)
    sold = by_status[ArticleStatus.sold]
    if seller.settled_payout_cents is not None:
        settlement = Settlement(
            sold_total_cents=seller.settled_sold_total_cents,
            commission_cents=seller.settled_commission_cents,
            open_offer_fee_cents=seller.settled_open_fee_cents,
            payout_cents=seller.settled_payout_cents,
        )
    else:
        settlement = settle(
            [a.price_cents for a in sold],
            rules_for(event, seller),
            fee_exempt=seller.fee_exempt,
            offer_fee_paid_at_entry=seller.offer_fee_paid_at_entry,
        )
    return Preview(
        seller,
        sold,
        by_status[ArticleStatus.available],
        by_status[ArticleStatus.returned] + by_status[ArticleStatus.withdrawn],
        settlement,
    )


def finish(
    s: Session,
    seller: Seller,
    *,
    returned_numbers: list[int],
    expected_payout_cents: int | None = None,
    client: str = "",
) -> Preview:
    """Commit: mark the ticked unsold articles returned and the seller settled.

    ``expected_payout_cents`` is the payout the volunteer saw; if a sale or storno changed it in
    the meantime we refuse, so nobody hands out a different amount than the one on screen.

    The transaction starts with BEGIN IMMEDIATE (SQLite write lock), so the payout re-check and the
    writes cannot interleave with a sale from another device.
    """
    s.rollback()  # end any read transaction so BEGIN IMMEDIATE can take the write lock
    s.execute(text("BEGIN IMMEDIATE"))
    s.refresh(seller)
    if seller.settled_at is not None:
        s.rollback()
        raise AbholungError("Dieser Verkäufer ist schon abgerechnet")
    before = preview(s, seller)
    if (
        expected_payout_cents is not None
        and before.settlement.payout_cents != expected_payout_cents
    ):
        s.rollback()
        raise AbholungError(
            "Die Abrechnung hat sich inzwischen geändert (neuer Verkauf oder Storno) – "
            "bitte die Zahlen unten prüfen und erneut abschließen"
        )
    ticked = set(returned_numbers)
    returned = [a for a in before.unsold if a.number in ticked]
    if returned:
        result = s.execute(
            update(Article)
            .where(
                Article.number.in_([a.number for a in returned]),
                Article.status == ArticleStatus.available,
            )
            .values(status=ArticleStatus.returned)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != len(returned):
            s.rollback()
            raise AbholungError(
                "Ein Artikel wurde inzwischen verkauft – bitte die Zahlen unten prüfen "
                "und erneut abschließen"
            )
    seller.settled_at = datetime.now()
    result = before.settlement
    seller.settled_sold_total_cents = result.sold_total_cents
    seller.settled_commission_cents = result.commission_cents
    seller.settled_open_fee_cents = result.open_offer_fee_cents
    seller.settled_payout_cents = result.payout_cents
    audit.log(
        s,
        "seller",
        seller.id,
        "settle",
        None,
        {
            "sold_total_cents": result.sold_total_cents,
            "commission_cents": result.commission_cents,
            "open_offer_fee_cents": result.open_offer_fee_cents,
            "payout_cents": result.payout_cents,
            "returned": [a.number for a in returned],
        },
        client,
    )
    s.commit()
    s.expire_all()  # the bulk UPDATE bypassed the ORM, so reload article statuses
    return preview(s, seller)


def settled_fee_status(seller: Seller, settlement: Settlement) -> str:
    """Fee line for the invoice, built from the frozen settlement, not from current settings."""
    if seller.fee_exempt:
        return "Gebührenfrei"
    if seller.offer_fee_paid_at_entry:
        paid = format_eur(seller.offer_fee_paid_cents or 0)
        return f"Angebotsgebühr {paid} bei der Annahme bezahlt"
    amount = format_eur(settlement.open_offer_fee_cents)
    return f"Angebotsgebühr {amount} wurde bei der Abrechnung abgezogen"
