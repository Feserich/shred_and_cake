"""Money handling. All amounts are integer cents; rates are integer basis points.

Floats are never used for money anywhere in the application.
"""

import re

BASIS_POINTS_PER_UNIT = 10_000  # 100 % == 10_000 bp

# German format: optional thousands dots in groups of three, optional comma + 1-2 decimals.
_EUR_RE = re.compile(r"^(?P<sign>-)?(?P<int>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<dec>\d{1,2}))?$")
# A single dot followed by 1-2 digits can only be a decimal point ("12.50" from an English
# keypad), since thousands groups always have three digits.
_DOT_DECIMAL_RE = re.compile(r"^(-?\d+)\.(\d{1,2})$")


class MoneyError(ValueError):
    """Raised when an amount cannot be parsed unambiguously."""


def parse_eur(text: str) -> int:
    """Parse a German formatted Euro amount into cents.

    Accepts surrounding whitespace, an optional '€' / 'EUR' and thousands dots:
    "60,00" -> 6000, " 2.545,00  " -> 254500, "15" -> 1500, "7,5" -> 750, "12.50" -> 1250.
    A dot is a thousands separator only when three digits follow ("1.500" -> 150000).
    Rejects ambiguous input such as "1,234" or "1.23,00".
    """
    s = text.strip().replace(" ", "")
    s = re.sub(r"(€|EUR|\ufffd|¤)$", "", s, flags=re.IGNORECASE).strip()
    s = s.replace(" ", "")
    s = _DOT_DECIMAL_RE.sub(r"\1,\2", s)
    m = _EUR_RE.match(s)
    if not m:
        raise MoneyError(f"„{text.strip()}“ ist kein gültiger Betrag – bitte z. B. 12,50 eingeben")
    euros = int(m["int"].replace(".", ""))
    dec = (m["dec"] or "").ljust(2, "0")
    cents = euros * 100 + int(dec or 0)
    return -cents if m["sign"] else cents


def format_eur(cents: int, symbol: bool = True) -> str:
    """Format cents as German Euro string: 254500 -> '2.545,00 €'."""
    if not isinstance(cents, int):
        raise TypeError("cents must be int")
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    text = f"{sign}{euros:,}".replace(",", ".") + f",{rest:02d}"
    return f"{text} €" if symbol else text


MAX_COMMISSION_BP = 10_000
PRICE_WARN_CENTS = 50_000  # prices above this need an explicit "Preis stimmt" confirmation


def parse_percent_bp(text: str) -> int:
    """Parse a percentage like '10', '12,5' or '7,25 %' into basis points."""
    s = text.strip().rstrip("%").strip()
    m = re.match(r"^(\d+)(?:[,.](\d{1,2}))?$", s)
    if not m:
        raise MoneyError(
            f"„{text.strip()}“ ist kein gültiger Prozentwert – bitte z. B. 10 eingeben"
        )
    return int(m[1]) * 100 + int((m[2] or "").ljust(2, "0"))


def format_percent_bp(bp: int) -> str:
    """Format basis points as German percentage: 1250 -> '12,5 %'."""
    whole, rest = divmod(bp, 100)
    if rest == 0:
        return f"{whole} %"
    return f"{whole},{rest:02d}".rstrip("0") + " %"


def commission(total_cents: int, rate_bp: int) -> int:
    """Commission on a total, rounded half up to whole cents (integer arithmetic only)."""
    if total_cents < 0 or rate_bp < 0:
        raise ValueError("total and rate must not be negative")
    return (total_cents * rate_bp + BASIS_POINTS_PER_UNIT // 2) // BASIS_POINTS_PER_UNIT
