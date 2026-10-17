"""Parser and validation for the shop article CSV (Latin-1/cp1252, ';'-separated)."""

import csv
import io
from dataclasses import dataclass, field

from .money import MoneyError, format_eur, parse_eur

# Canonical field -> accepted header spellings. Headers are compared after _norm(), so case,
# umlauts/ß, spaces and punctuation do not matter ("Grösse" == "groesse" == "GRÖSSE").
_COLUMNS = {
    "number": ("Artikelnummer", "Nr", "Nummer", "Art.-Nr.", "Artikel-Nr", "Lfd. Nr", "Pos"),
    "shop_ref": ("Ihre Artikelnummer", "Ihre Nr", "Ihre Art.-Nr.", "Eigene Artikelnummer", "Interne Nummer"),
    "description": ("Artikelname", "Name", "Bezeichnung", "Artikel", "Beschreibung", "Artikelbezeichnung"),
    "brand": ("Marke", "Mark", "Hersteller", "Brand"),
    "size": ("Grösse", "Größe", "Gr.", "Länge", "Size"),
    "color": ("Farbe", "Color", "Colour"),
    "price": ("Preis_1", "Preis", "VK", "VK-Preis", "Verkaufspreis", "Preis EUR", "Preis in EUR", "Price"),
}
_REQUIRED = ("number", "description", "price")


@dataclass
class ImportRow:
    line: int
    number: int | None = None
    shop_ref: str = ""
    description: str = ""
    brand: str = ""
    size: str = ""
    color: str = ""
    price_cents: int | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class ParsedCsv:
    rows: list[ImportRow] = field(default_factory=list)
    declared_total: int | None = None
    encoding: str = ""
    errors: list[str] = field(default_factory=list)  # file-level problems

    @property
    def computed_total(self) -> int:
        return sum(r.price_cents or 0 for r in self.rows)

    @property
    def total_mismatch(self) -> bool:
        return self.declared_total is not None and self.declared_total != self.computed_total

    @property
    def has_errors(self) -> bool:
        return bool(self.errors) or any(r.errors for r in self.rows)


def _norm(name: str) -> str:
    """Fold a header to a comparable key: lowercase, umlauts/ß expanded, only letters and digits."""
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        name = name.lower().replace(src, dst)
    return "".join(c for c in name if c.isalnum())


def decode(data: bytes) -> tuple[str, str]:
    """Decode as UTF-8 (with or without BOM) if valid, otherwise as cp1252, then Latin-1."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def parse_shop_csv(data: bytes) -> ParsedCsv:
    text, encoding = decode(data)
    result = ParsedCsv(encoding=encoding)
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if header is None:
        result.errors.append("Die Datei ist leer")
        return result
    names = [_norm(h) for h in header]
    index: dict[str, int] = {}
    for key, spellings in _COLUMNS.items():
        for spelling in spellings:
            if _norm(spelling) in names:
                index[key] = names.index(_norm(spelling))
                break
    missing = [_COLUMNS[k][0] for k in _REQUIRED if k not in index]
    if missing:
        result.errors.append("Spalten fehlen: " + ", ".join(missing))
        return result

    def cell(row: list[str], key: str) -> str:
        i = index.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    for line, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue
        if any(c.strip().rstrip(":").lower() == "summe" for c in raw):
            amounts = [c for c in raw if c.strip() and c.strip().rstrip(":").lower() != "summe"]
            try:
                result.declared_total = parse_eur(amounts[-1]) if amounts else None
            except MoneyError:
                result.errors.append(f"Zeile {line}: Summe nicht lesbar")
            continue
        row = ImportRow(
            line=line,
            shop_ref=cell(raw, "shop_ref"),
            description=cell(raw, "description"),
            brand=cell(raw, "brand"),
            size=cell(raw, "size"),
            color=cell(raw, "color"),
        )
        number_text = cell(raw, "number")
        if number_text.isdigit():
            row.number = int(number_text)
        else:
            row.errors.append("Artikelnummer fehlt oder ist keine Zahl")
        if not row.description:
            row.errors.append("Artikelname fehlt")
        try:
            row.price_cents = parse_eur(cell(raw, "price"))
            if row.price_cents <= 0:
                row.errors.append("Preis muss größer als 0 sein")
        except MoneyError:
            row.errors.append(f"Preis nicht lesbar: {cell(raw, 'price')!r}")
        result.rows.append(row)

    if not result.rows:
        result.errors.append("Keine Artikel in der Datei gefunden")
    return result


def validate(parsed: ParsedCsv, range_start: int, range_end: int) -> None:
    """Add per-row errors for numbers outside the shop's range and duplicate numbers."""
    seen: dict[int, int] = {}
    for row in parsed.rows:
        if row.number is None:
            continue
        if not range_start <= row.number <= range_end:
            row.errors.append(
                f"Nummer {row.number} liegt außerhalb des Bereichs {range_start}–{range_end}"
            )
        if row.number in seen:
            row.errors.append(f"Nummer doppelt (auch in Zeile {seen[row.number]})")
        else:
            seen[row.number] = row.line
    if parsed.total_mismatch:
        parsed.errors.append(
            f"Summe der Datei weicht ab: Datei {format_eur(parsed.declared_total)}, "
            f"berechnet {format_eur(parsed.computed_total)}"
        )
