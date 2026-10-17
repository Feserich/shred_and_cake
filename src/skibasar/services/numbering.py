"""Article number assignment and shop number range validation."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Article, Event, Seller, SellerType


class RangeError(ValueError):
    pass


def shop_ranges(s: Session, exclude_seller_id: int | None = None) -> list[tuple[int, int, str]]:
    q = select(Seller).where(Seller.type == SellerType.shop)
    ranges = []
    for shop in s.scalars(q):
        if shop.id == exclude_seller_id or shop.number_range_start is None:
            continue
        ranges.append((shop.number_range_start, shop.number_range_end, shop.name))
    return sorted(ranges)


def validate_shop_range(
    s: Session, start: int, end: int, exclude_seller_id: int | None = None
) -> None:
    """Shop ranges must be well-formed, not overlap each other or used private numbers."""
    if start < 0 or end < start:
        raise RangeError("Ungültiger Nummernbereich")
    for a, b, name in shop_ranges(s, exclude_seller_id):
        if start <= b and a <= end:
            raise RangeError(f"Nummernbereich überschneidet sich mit {name} ({a}–{b})")
    clash = s.scalar(
        select(Article.number)
        .join(Seller)
        .where(Seller.type == SellerType.private, Article.number.between(start, end))
        .limit(1)
    )
    if clash is not None:
        raise RangeError(f"Nummer {clash} ist bereits an einen Privatverkäufer vergeben")


def next_private_number(s: Session) -> int:
    """Next number after the highest private number, skipping over shop ranges."""
    event = s.get(Event, 1)
    highest = s.scalar(
        select(func.max(Article.number)).join(Seller).where(Seller.type == SellerType.private)
    )
    candidate = event.private_number_start if highest is None else highest + 1
    candidate = max(candidate, event.private_number_start)
    for a, b, _ in shop_ranges(s):  # sorted, so one pass skips consecutive ranges
        if a <= candidate <= b:
            candidate = b + 1
    return candidate


def is_in_shop_range(seller: Seller, number: int) -> bool:
    return (
        seller.number_range_start is not None
        and seller.number_range_start <= number <= seller.number_range_end
    )
