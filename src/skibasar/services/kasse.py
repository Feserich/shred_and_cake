"""Checkout (Kasse): look up articles, complete sales atomically, storno."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Article, ArticleStatus, Sale, Seller
from . import audit


class KasseError(ValueError):
    pass


def lookup(s: Session, number: int, in_cart: list[int]) -> Article:
    """The article to put in the cart, or a KasseError with a plain German reason."""
    article = s.scalar(select(Article).where(Article.number == number))
    if article is None:
        raise KasseError(f"Nummer {number} gibt es nicht")
    if number in in_cart:
        raise KasseError(f"Nummer {number} ist schon in diesem Verkauf")
    if article.status == ArticleStatus.sold:
        raise KasseError(f"Nummer {number} ist schon verkauft")
    if article.status != ArticleStatus.available:
        label = "zurückgegeben" if article.status == ArticleStatus.returned else "zurückgezogen"
        raise KasseError(f"Nummer {number} wurde {label} und darf nicht verkauft werden")
    if article.seller.settled_at is not None:
        raise KasseError(f"Der Verkäufer von Nummer {number} ist bereits abgerechnet")
    return article


def load_cart(s: Session, numbers: list[int]) -> list[Article]:
    """Cart articles in the order they were scanned; unknown numbers are dropped."""
    found = {a.number: a for a in s.scalars(select(Article).where(Article.number.in_(numbers)))}
    return [found[n] for n in numbers if n in found]


def complete_sale(s: Session, numbers: list[int], client: str = "") -> Sale:
    """Mark all articles sold in one transaction; refuse if any is no longer available.

    The conditional UPDATE is the guard against double-selling: it only touches rows that are
    still ``available`` and whose seller is not yet settled, so a second device that sold the same
    article first, or settled the seller a moment ago, makes the row count come up short and the
    whole sale is rolled back.
    """
    if not numbers:
        raise KasseError("Der Verkauf ist leer")
    if len(set(numbers)) != len(numbers):
        raise KasseError("Eine Nummer kommt doppelt vor")
    articles = load_cart(s, numbers)
    if len(articles) != len(numbers):
        raise KasseError("Eine Nummer gibt es nicht")
    for a in articles:
        if a.status != ArticleStatus.available:
            raise KasseError(f"Nummer {a.number} ist schon verkauft – bitte entfernen")
        if a.seller.settled_at is not None:
            raise KasseError(f"Der Verkäufer von Nummer {a.number} ist bereits abgerechnet")
    sale = Sale(total_cents=sum(a.price_cents for a in articles))
    s.add(sale)
    s.flush()
    result = s.execute(
        update(Article)
        .where(
            Article.number.in_(numbers),
            Article.status == ArticleStatus.available,
            Article.seller_id.in_(select(Seller.id).where(Seller.settled_at.is_(None))),
        )
        .values(status=ArticleStatus.sold, sale_id=sale.id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != len(numbers):
        s.rollback()
        raise KasseError(
            "Mindestens ein Artikel wurde gerade anderswo verkauft oder abgerechnet – bitte prüfen"
        )
    audit.log(
        s,
        "sale",
        sale.id,
        "create",
        None,
        {"numbers": numbers, "total_cents": sale.total_cents},
        client,
    )
    s.commit()
    s.refresh(sale)
    return sale


def cancel_sale(s: Session, sale: Sale, client: str = "") -> None:
    """Storno: keep the sale record, free its articles again."""
    if sale.cancelled:
        raise KasseError("Dieser Verkauf ist schon storniert")
    articles = list(sale.articles)
    for a in articles:
        if a.seller.settled_at is not None:
            raise KasseError(
                f"Storno nicht möglich: Der Verkäufer von Nummer {a.number} ist bereits abgerechnet"
            )
    for a in articles:
        a.status = ArticleStatus.available
        a.sale_id = None
    sale.cancelled = True
    audit.log(
        s,
        "sale",
        sale.id,
        "cancel",
        {"numbers": [a.number for a in articles], "total_cents": sale.total_cents},
        None,
        client,
    )
    s.commit()
