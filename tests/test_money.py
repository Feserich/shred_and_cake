import pytest

from skibasar.money import (
    MoneyError,
    commission,
    format_eur,
    format_percent_bp,
    parse_eur,
    parse_percent_bp,
)


@pytest.mark.parametrize(
    "text,cents",
    [
        ("60,00", 6000),
        (" 60,00  ", 6000),
        ("2.545,00", 254500),
        (" 2.545,00  ", 254500),
        ("15", 1500),
        ("7,5", 750),
        ("0,01", 1),
        ("0", 0),
        ("12,34 €", 1234),
        ("12,34€", 1234),
        ("12,34 EUR", 1234),
        ("1.000.000,99", 100000099),
        ("-3,50", -350),
    ],
)
def test_parse_eur(text, cents):
    assert parse_eur(text) == cents


@pytest.mark.parametrize(
    "text", ["", " ", "abc", "1.5", "60.00", "1,234", "1.23,00", "12.3456,00", "1,", ",50", "--1"]
)
def test_parse_eur_rejects_ambiguous(text):
    with pytest.raises(MoneyError):
        parse_eur(text)


@pytest.mark.parametrize(
    "cents,text",
    [
        (0, "0,00 €"),
        (1, "0,01 €"),
        (6000, "60,00 €"),
        (254500, "2.545,00 €"),
        (100000099, "1.000.000,99 €"),
        (-350, "-3,50 €"),
        (-5, "-0,05 €"),
    ],
)
def test_format_eur(cents, text):
    assert format_eur(cents) == text
    assert parse_eur(text) == cents


def test_format_eur_rejects_float():
    with pytest.raises(TypeError):
        format_eur(1.5)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text,bp", [("10", 1000), ("12,5", 1250), ("7,25 %", 725), ("0", 0), ("100", 10000)]
)
def test_percent(text, bp):
    assert parse_percent_bp(text) == bp


def test_format_percent():
    assert format_percent_bp(1000) == "10 %"
    assert format_percent_bp(1250) == "12,5 %"
    assert format_percent_bp(725) == "7,25 %"


@pytest.mark.parametrize(
    "total,bp,expected",
    [
        (10000, 1000, 1000),  # 10 % of 100,00 = 10,00
        (5, 1000, 1),  # 0,5 ct rounds half up -> 1 ct
        (4, 1000, 0),  # 0,4 ct -> 0
        (15, 1000, 2),  # 1,5 ct -> 2
        (254500, 1250, 31813),  # 318,125 -> 318,13
        (333, 3333, 111),  # 110,9889 -> 111
        (0, 1000, 0),
        (12345, 0, 0),
    ],
)
def test_commission_round_half_up(total, bp, expected):
    assert commission(total, bp) == expected


def test_commission_rejects_negative():
    with pytest.raises(ValueError):
        commission(-1, 1000)
