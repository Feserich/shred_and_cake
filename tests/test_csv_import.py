from pathlib import Path

import pytest
from sqlalchemy import select

from skibasar.csv_import import parse_shop_csv, validate
from skibasar.models import Article, ArticleStatus, AuditLog, Seller
from skibasar.services import shops
from skibasar.services.numbering import RangeError

FIXTURE = Path(__file__).parent / "fixtures" / "shop_kraemer.csv"
HEADER = "Artikelnummer;Ihre Artikelnummer;Artikelname;Marke;Grösse;Farbe;Preis_1\r\n"


def csv_bytes(*lines: str, enc="cp1252") -> bytes:
    return (HEADER + "".join(line + "\r\n" for line in lines)).encode(enc)


def test_real_file():
    parsed = parse_shop_csv(FIXTURE.read_bytes())
    validate(parsed, 1000, 1999)
    assert parsed.encoding == "cp1252"
    assert len(parsed.rows) == 41
    assert parsed.computed_total == 254500
    assert parsed.declared_total == 254500
    assert not parsed.has_errors
    assert parsed.rows[2].brand == "Völkl"


def test_utf8_and_padded_prices():
    parsed = parse_shop_csv(csv_bytes("5;5;Ski;Völkl;90;; 2.545,00  ", enc="utf-8-sig"))
    assert parsed.encoding == "utf-8-sig"
    assert parsed.rows[0].price_cents == 254500
    assert parsed.rows[0].brand == "Völkl"


def test_row_errors():
    parsed = parse_shop_csv(
        csv_bytes(
            "1;1;Ski;;;;10,00",
            "1;1;Ski;;;;10,00",
            "x;;Ski;;;;1",
            ";;;;;;",
            "7;7;;;;;abc",
            "9999;;Ski;;;;5,00",
        )
    )
    validate(parsed, 0, 100)
    errors = [r.errors for r in parsed.rows]
    assert any("doppelt" in e for e in errors[1])
    assert "Artikelnummer fehlt" in errors[2][0]
    assert any("Artikelname" in e for e in errors[3]) and any("Preis" in e for e in errors[3])
    assert any("außerhalb" in e for e in errors[4])
    assert parsed.has_errors


def test_total_mismatch_and_missing_columns():
    parsed = parse_shop_csv(csv_bytes("1;1;Ski;;;;10,00", ";;;Summe:;;;99,00"))
    validate(parsed, 0, 10)
    assert parsed.total_mismatch and parsed.has_errors
    assert parse_shop_csv(b"foo;bar\r\n1;2\r\n").errors
    assert parse_shop_csv(b"").errors


@pytest.fixture
def shop(session):
    return shops.save_shop(session, None, name="Krämer", range_start=1000, range_end=1999)


def test_import_roundtrip_and_reimport(session, shop):
    parsed = parse_shop_csv(FIXTURE.read_bytes())
    validate(parsed, 1000, 1999)
    diff = shops.apply_import(session, shop, parsed)
    assert len(diff.new) == 41
    arts = session.scalars(select(Article)).all()
    assert len(arts) == 41 and sum(a.price_cents for a in arts) == 254500

    # re-import with one changed price and one removed article
    data = FIXTURE.read_bytes().replace(
        b"1000;1000;Ski;Head;130;; 60,00", b"1000;1000;Ski;Head;130;; 65,00"
    )
    data = data.replace(b"1040;1040;Skischuh;Firefly;23,0 / EU36;; 30,00 \x80 \r\n", b"")
    parsed2 = parse_shop_csv(data)
    parsed2.declared_total = None
    validate(parsed2, 1000, 1999)
    diff2 = shops.diff_import(session, shop, parsed2)
    assert (len(diff2.changed), len(diff2.removed), len(diff2.unchanged)) == (1, 1, 39)
    shops.apply_import(session, shop, parsed2)
    assert session.scalar(select(Article).where(Article.number == 1000)).price_cents == 6500
    assert session.scalar(select(Article).where(Article.number == 1040)) is None
    assert session.scalars(select(AuditLog).where(AuditLog.action == "import")).all()


def test_import_blocked_by_errors_and_sold_articles(session, shop):
    bad = parse_shop_csv(csv_bytes("1;1;Ski;;;;10,00"))
    validate(bad, 1000, 1999)
    with pytest.raises(RangeError):
        shops.apply_import(session, shop, bad)
    assert session.scalars(select(Article)).all() == []

    good = parse_shop_csv(csv_bytes("1000;1000;Ski;;;;10,00"))
    validate(good, 1000, 1999)
    shops.apply_import(session, shop, good)
    session.scalar(select(Article)).status = ArticleStatus.sold
    session.commit()
    changed = parse_shop_csv(csv_bytes("1000;1000;Ski;;;;12,00"))
    validate(changed, 1000, 1999)
    with pytest.raises(RangeError):
        shops.apply_import(session, shop, changed)


def test_number_owned_by_other_seller(session, shop):
    other = shops.save_shop(session, None, name="Anderer", range_start=2000, range_end=2999)
    session.add(Article(number=2000, seller_id=other.id, description="x", price_cents=1))
    session.commit()
    parsed = parse_shop_csv(csv_bytes("2000;2000;Ski;;;;10,00"))
    validate(parsed, 1000, 2999)
    diff = shops.diff_import(session, shop, parsed)
    assert parsed.rows[0].errors and not diff.new


def test_shop_range_overlap_rejected(session, shop):
    with pytest.raises(RangeError):
        shops.save_shop(session, None, name="B", range_start=1500, range_end=2500)
    assert len(session.scalars(select(Seller)).all()) == 1
