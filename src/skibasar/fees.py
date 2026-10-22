"""Settlement calculation for a single seller."""

from dataclasses import dataclass

from .money import commission


@dataclass(frozen=True)
class FeeRules:
    offer_fee_cents: int
    commission_bp: int
    per_article: bool = False  # private sellers pay the offer fee for every article


@dataclass(frozen=True)
class Settlement:
    sold_total_cents: int
    commission_cents: int
    open_offer_fee_cents: int
    payout_cents: int  # negative: the seller has to pay the club

    @property
    def seller_pays(self) -> bool:
        return self.payout_cents < 0


def paid_at_entry_cents(previous: int | None, *, paid: bool, fee_cents: int) -> int | None:
    """Fee cash taken at entry: the current fee when first marked paid, then kept as is."""
    if not paid:
        return None
    return fee_cents if previous is None else previous


def settle(
    sold_prices_cents: list[int],
    rules: FeeRules,
    *,
    fee_exempt: bool,
    offer_fee_paid_at_entry: bool,
    article_count: int = 0,
) -> Settlement:
    """Compute what a seller receives: sold total minus commission minus open offer fee.

    Commission is computed once on the seller's sold total, never per article.
    The offer fee is charged once, or per offered article (``article_count``) if the rules say so.
    Fee-exempt sellers pay neither offer fee nor commission.
    """
    sold_total = sum(sold_prices_cents)
    if fee_exempt:
        comm, open_fee = 0, 0
    else:
        comm = commission(sold_total, rules.commission_bp)
        units = article_count if rules.per_article else 1
        open_fee = 0 if offer_fee_paid_at_entry else rules.offer_fee_cents * units
    return Settlement(
        sold_total_cents=sold_total,
        commission_cents=comm,
        open_offer_fee_cents=open_fee,
        payout_cents=sold_total - comm - open_fee,
    )
