import pytest

from skibasar.models import Article, Event, Seller, SellerType
from skibasar.services.numbering import (
    RangeError,
    is_in_shop_range,
    next_private_number,
    validate_shop_range,
)


def add_shop(s, name, start, end):
    shop = Seller(type=SellerType.shop, name=name, number_range_start=start, number_range_end=end)
    s.add(shop)
    s.commit()
    return shop


def add_private_article(s, number):
    seller = Seller(type=SellerType.private, name="Muster")
    s.add(seller)
    s.add(Article(number=number, seller=seller, description="Ski", price_cents=1000))
    s.commit()


def test_first_private_number_is_start(session):
    assert next_private_number(session) == 0
    session.get(Event, 1).private_number_start = 1
    assert next_private_number(session) == 1


def test_private_numbers_increment(session):
    add_private_article(session, 0)
    add_private_article(session, 1)
    assert next_private_number(session) == 2


def test_private_numbers_skip_shop_ranges(session):
    add_shop(session, "Krämer", 2, 5)
    add_shop(session, "Baumhauer", 6, 9)
    add_private_article(session, 0)
    add_private_article(session, 1)
    assert next_private_number(session) == 10


def test_shop_articles_do_not_affect_private_counter(session):
    shop = add_shop(session, "Krämer", 1000, 1999)
    session.add(Article(number=1000, seller=shop, description="Ski", price_cents=6000))
    session.commit()
    assert next_private_number(session) == 0


def test_overlapping_shop_ranges_rejected(session):
    add_shop(session, "Krämer", 1000, 1999)
    with pytest.raises(RangeError, match="Krämer"):
        validate_shop_range(session, 1500, 2500)
    validate_shop_range(session, 2000, 2999)


def test_shop_range_can_be_edited_in_place(session):
    shop = add_shop(session, "Krämer", 1000, 1999)
    validate_shop_range(session, 1000, 1499, exclude_seller_id=shop.id)


def test_invalid_range_rejected(session):
    with pytest.raises(RangeError):
        validate_shop_range(session, 2000, 1000)


def test_shop_range_must_not_cover_used_private_numbers(session):
    add_private_article(session, 5)
    with pytest.raises(RangeError, match="5"):
        validate_shop_range(session, 0, 99)


def test_is_in_shop_range():
    shop = Seller(type=SellerType.shop, name="K", number_range_start=1000, number_range_end=1999)
    assert is_in_shop_range(shop, 1000) and is_in_shop_range(shop, 1999)
    assert not is_in_shop_range(shop, 2000)
    assert not is_in_shop_range(Seller(name="P"), 5)
