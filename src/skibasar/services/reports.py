"""Gesamtabrechnung: totals over all sellers, reconciled to the cent."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Article, ArticleStatus, Event, Sale, Seller, SellerType
from . import abholung


@dataclass
class GroupTotals:
    sellers: int = 0
    settled: int = 0
    sold_cents: int = 0  # of settled sellers
    commission_cents: int = 0
    deducted_fee_cents: int = 0
    payout_cents: int = 0  # negative: sellers who paid the club
    fee_at_entry_cents: int = 0  # collected in cash at Annahme (all sellers, not only settled)


@dataclass(frozen=True)
class OpenSeller:
    seller: Seller
    sold_cents: int
    payout_cents: int


@dataclass(frozen=True)
class Report:
    sales_count: int
    cancelled_count: int
    sales_total_cents: int  # valid (not cancelled) sales
    articles_by_status: dict[ArticleStatus, int]
    groups: dict[SellerType, GroupTotals]
    open_sellers: list[OpenSeller]
    open_sold_cents: int  # sold, but the seller has not been settled yet

    @property
    def settled_sold_cents(self) -> int:
        return sum(g.sold_cents for g in self.groups.values())

    @property
    def commission_cents(self) -> int:
        return sum(g.commission_cents for g in self.groups.values())

    @property
    def deducted_fee_cents(self) -> int:
        return sum(g.deducted_fee_cents for g in self.groups.values())

    @property
    def payout_cents(self) -> int:
        return sum(g.payout_cents for g in self.groups.values())

    @property
    def fee_at_entry_cents(self) -> int:
        return sum(g.fee_at_entry_cents for g in self.groups.values())

    @property
    def club_income_cents(self) -> int:
        return self.commission_cents + self.deducted_fee_cents + self.fee_at_entry_cents

    @property
    def reconciles(self) -> bool:
        """Σ sales == Σ payouts + Σ commission + Σ deducted fees (settled + still open)."""
        settled_ok = (
            self.settled_sold_cents
            == self.payout_cents + self.commission_cents + self.deducted_fee_cents
        )
        all_sold = self.settled_sold_cents + self.open_sold_cents
        return settled_ok and all_sold == self.sales_total_cents


def build(s: Session) -> Report:
    event = s.get(Event, 1)
    sales_total = s.scalar(
        select(func.coalesce(func.sum(Sale.total_cents), 0)).where(Sale.cancelled.is_(False))
    )
    sales_count = s.scalar(select(func.count()).select_from(Sale).where(Sale.cancelled.is_(False)))
    cancelled = s.scalar(select(func.count()).select_from(Sale).where(Sale.cancelled.is_(True)))
    by_status = dict.fromkeys(ArticleStatus, 0)
    for st, n in s.execute(select(Article.status, func.count()).group_by(Article.status)):
        by_status[st] = n

    groups = {t: GroupTotals() for t in SellerType}
    open_sellers: list[OpenSeller] = []
    open_sold = 0
    for seller in s.scalars(select(Seller).order_by(Seller.name, Seller.id)):
        g = groups[seller.type]
        g.sellers += 1
        rules = abholung.rules_for(event, seller)
        if seller.offer_fee_paid_at_entry and not seller.fee_exempt:
            g.fee_at_entry_cents += rules.offer_fee_cents
        p = abholung.preview(s, seller)
        r = p.settlement
        if seller.settled_at is not None:
            g.settled += 1
            g.sold_cents += r.sold_total_cents
            g.commission_cents += r.commission_cents
            g.deducted_fee_cents += r.open_offer_fee_cents
            g.payout_cents += r.payout_cents
        else:
            open_sold += r.sold_total_cents
            open_sellers.append(OpenSeller(seller, r.sold_total_cents, r.payout_cents))
    return Report(sales_count, cancelled, sales_total, by_status, groups, open_sellers, open_sold)
