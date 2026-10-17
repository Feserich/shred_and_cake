# Plan: New Ski Basar Web Application (sce_skibasar)

## Context
The ski club runs its basar on "CasaBazar20", an old MS Access 2003 app that only runs on one old laptop and is hard to use. We replace it with an offline web app that anyone can use: FastAPI with server-rendered pages, shipped as a pre-built executable for Windows and Linux, and safe with money (integer cents only). It has a CSV fallback so the basar can carry on by hand if the software fails.

The repo currently holds only `README.md` and the reference material in `ms_access/`:
- `CSV_Skibazar.csv`: `;`-separated, **Latin-1/cp1252**, CRLF line endings. Header `Artikelnummer;Ihre Artikelnummer;Artikelname;Marke;Grösse;Farbe;Preis_1`. Prices are German formatted with padding (`" 60,00  "`, `"2.545,00"`). The file ends with an empty row and a `Summe:` row, which the import must skip (and can use as a check against the imported total).
- The old manual (`Anleitung Skibasarprogramm.odt`) describes the same flow: Annahme → Verkauf → Abholung → Gesamtabrechnung. It also covers fees paid at entry or left open ("off. Geb."), fee exemption for the teaching team, a separate "Artikel suchen" screen to fix mistakes, and the old "Abbrechen vs. Tür" trap. The new UI must make preview and commit explicit, separate steps.
- Old MDB tables: `T_KUNDEN`, `T_UMSATZ` (with `PREIS_1`, `PREIS_2`, `Preis_TAT`) and `T_Parameter`. These are for reference only. We don't migrate the data.

### Decisions confirmed with the user
| Topic | Decision |
|---|---|
| Devices | **1 laptop runs the server** and does entry and checkout. Support phones connect over local WiFi through the browser (subset of features) |
| Printing | **Normal A4 printer** using the browser print dialog and print-optimized HTML (`@media print`) |
| Article numbers (individual sellers) | **The system assigns the next free number** (global counter starting at 0). The volunteer sticks on the matching pre-printed tag |
| Pricing | **Fixed price only.** Tag price = sale price, no Preis 2 or negotiation |
| Offer fee | **Per seller:** paid in cash at entry *or* left open and deducted at payout |
| Fee rules (separate values for shop and individual) | Flat offer fee per seller, commission % on sold total, fee exemption flag per seller |
| Barcodes | None. Numbers are typed (keyboard-optimized: number + Enter) |
| Language | UI and printouts in **German only**. Code and comments in English |

## Architecture
- **Backend:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2 (or SQLModel) on **SQLite** (WAL mode, one file in a data directory next to the executable).
- **Frontend:** Jinja2 templates + **HTMX** + **Alpine.js** (small, for input masks, focus handling and formatting) + a small classless CSS (e.g. Pico.css) customized by `app.css`. All assets are **vendored** into `static/` (no CDN, the app must work fully offline). There is no JS build step. Layout is responsive so phones work. See "UI/UX principles" below.
- **Single process, single DB.** All writes go through one server, so phones and the laptop can't conflict. Checkout marks items sold in one transaction and rejects items that are already sold.
- **Packaging:** PyInstaller one-file builds. A Windows exe has to be built on Windows, so each build is done **locally on the target OS** (Windows build on a Windows machine, Linux build on a Linux machine) with the same `packaging/skibasar.spec`. There is no CI. On start, the exe opens the browser at `http://localhost:8000` and prints and shows the LAN URL plus a QR code for phones.
- **Access control:** a simple event PIN for LAN clients (localhost is exempt) and an **admin PIN** for destructive actions (delete or reset data, edit settled sellers).

## UI/UX principles
The users are club volunteers with no technical background, often working fast and under time pressure. The app must be very easy to use and look modern.

**Layout and navigation**
- One task per screen. A persistent top bar with the main steps (Annahme → Kasse → Abholung → Übersicht) and the current step highlighted.
- Large touch targets (at least 44 px), large type for numbers and prices, generous spacing. The same layout works on the laptop and on phones.
- A friendly empty state on every screen that says what to do next.

**Visual design (small design system in `app.css`)**
- A fixed palette, spacing scale and button styles, built on Pico.css variables. Light and dark theme, with enough contrast to read in a bright hall.
- Status colors used consistently: green = sold/ok, red = error/blocked, amber = fee open or needs attention, grey = withdrawn/returned.
- Icons are inline SVG (vendored, no CDN).

**Input masks and forms**
- Price field: accepts "60", "60,5" and "60,00 €" and shows the formatted value on blur. Parsing goes through `money.py` on the server, so client and server never disagree.
- Number fields are numeric (phone shows the number keypad). Autofocus lands on the first field. Enter moves to the next field, and after saving the cursor returns to the first field.
- Autocomplete (`datalist`) for brand, size and color from earlier entries.
- Inline validation with plain German messages (for example "Diese Nummer ist schon verkauft"), never technical errors or stack traces.

**Feedback and safety**
- Every action gives a visible success cue (brief green flash or toast). Errors at the checkout are large, red and optionally with a sound, so a mistake is noticed without reading.
- Undo for the last entry at Annahme and Kasse.
- Destructive actions need a confirmation dialog with clear wording that names what will happen (for example "Verkauf Nr. 12 wirklich stornieren? 3 Artikel werden wieder frei.").
- Preview and commit are separate steps (see Abholung).

**Help**
- A short hint on each screen and a link to the Anleitung. No jargon in labels (German everyday words).

**Accessibility**
- Visible focus states, labels on all fields, readable minimum font size on phones, usable without a mouse.

**Validation of the design**
- A click-through with 2–3 non-technical volunteers happens after M4, well before the Probe-Basar.

## Money rules (core, fully unit-tested)
- Every amount is an `int` in cents. The commission rate is an `int` in **basis points** (10 % = 1000). There are no floats anywhere.
- One module `money.py` handles everything:
  - `parse_eur("2.545,00") -> 254500`: strict parsing that accepts German formatting, padding and optionally `€`, and rejects anything ambiguous.
  - `format_eur(254500) -> "2.545,00 €"`.
  - `commission(total_cents, bp)`: integer arithmetic with **round half up** to a whole cent, applied **once per seller on their sold total** (never per article).
- Settlement per seller:
  `payout = sold_total − commission − (offer_fee if open and not exempt)`.
  The payout can be negative, for example when nothing sold and the fee is still open. The invoice then shows "Seller pays X".

## Data model (`models.py`)
- **Event:** name, date, `private_number_start` (default 0), `offer_fee_private_cents`, `commission_private_bp`, `offer_fee_shop_cents`, `commission_shop_bp`.
- **Seller:** id, type (`private`|`shop`), name, first name, phone/email/address (optional), `number_range_start/end` (shops), `fee_exempt`, `offer_fee_paid_at_entry`, `settled_at`, notes.
- **Article:** `number` (unique), seller_id, description, brand, size, color, `price_cents`, `shop_ref` ("Ihre Artikelnummer"), status (`available` | `sold` | `returned` | `withdrawn`), sale_id, timestamps.
- **Sale:** id, created_at, total_cents, cancelled flag (storno keeps the record and frees the articles).
- **AuditLog:** timestamp, client (IP or device), entity, entity_id, action, before/after JSON. Every manual edit is recorded.
- Validation: shop ranges must not overlap each other or the private number range. A new private number is the next number after the highest one used that is not inside a shop range.

## Screens / workflow (German UI)
1. **Einstellungen (Setup):** event parameters and fees. Shops are created with their number ranges.
2. **Händler-Import:** upload the shop CSV → auto-detect the encoding (cp1252/UTF-8) → **preview table with errors** (number outside the shop's range, duplicates, unreadable price, missing name) → compare against the `Summe:` row → confirm import. The import can be re-run per shop: the preview shows a diff before replacing.
3. **Annahme (entry):** a short seller form, then fast article entry. The next number is shown in large type: fill in description, brand, size and price, press Enter, and the next number appears. "Gebühr bezahlt" checkbox. **Print seller list** (A4: seller data, articles, prices, fee status, signature line).
4. **Kasse (checkout):** type the number + Enter → the line appears with its price. Duplicates, already sold, unknown and withdrawn numbers trigger a clear red warning. Running total, optional "gegeben/Rückgeld" calculation, and a big **"Verkauf abschließen"** button. After that, an optional receipt print. A **Storno** of the last or any sale is possible.
5. **Abholung / Abrechnung (pickup and settlement):** search by name, seller number or article number. The screen shows sold and unsold items, and unsold items are ticked as returned. It shows the calculation (sold total, commission, open fee, payout). **Preview is read-only. Only "Abrechnung abschließen" saves anything**, which removes the old Abbrechen/Tür trap. Prints an A4 invoice with a signature line. Shops use the same flow.
6. **Übersicht / Tabellen (overview):** searchable and filterable tables for sellers, articles and sales with inline edit, available at any time and in any phase. Changes are logged in the audit log. Settled sellers need the admin PIN to edit.
7. **Gesamtabrechnung (final report):** totals for sales, commission, fees collected at entry vs. deducted, payouts to private sellers and to shops, and a list of sellers who have not picked up yet. Printable.
8. **Phone subset:** Annahme, Artikel suchen and Kasse use the same pages in a responsive layout.

## Fallback & data safety (`backup.py`)
- **Append-only journal CSV** (`data/journal.csv`): one line per write event (sale, storno, article change, settlement), flushed and fsynced right away. A human can replay it by hand.
- **CSV snapshots** of `sellers.csv`, `articles.csv` and `sales.csv` every few minutes and after every settlement. They are written `;`-separated in **UTF-8 with BOM** so German Excel/LibreOffice opens them cleanly, with amounts in both cents and as `"60,00"`.
- **SQLite online backups** (`sqlite3.backup`) as rotating timestamped copies, plus an "Export to USB/folder" button.
- **Printable "Notfallliste" (emergency list):** all articles sorted by number with price and seller. It is printed before selling starts, so checkout could continue on paper.
- A short German one-page "Notfallplan" in the docs explains the manual procedure.

## Project layout
```
pyproject.toml          # uv-managed; ruff, pytest config
src/skibasar/
  main.py               # FastAPI app factory, startup (open browser, LAN URL, QR)
  config.py             # data dir, port, PINs
  db.py  models.py      # SQLAlchemy engine/session, ORM models
  money.py  fees.py     # cents parsing/formatting, settlement calculation
  csv_import.py         # shop CSV parser + validation
  backup.py             # journal, snapshots, sqlite backups
  services/             # numbering, checkout, settlement, audit
  routers/              # setup, annahme, kasse, abholung, tabellen, reports
  templates/            # Jinja2 (base, screens, print/*.html)
  static/               # vendored htmx.min.js, alpine.min.js, pico.css, app.css, app.js, icons
tests/                  # unit + TestClient integration tests, fixtures incl. the example CSV
packaging/skibasar.spec # PyInstaller spec
packaging/build.sh      # local build script (Linux); build.ps1 for Windows
docs/Anleitung.md       # German user guide + Notfallplan
```
Housekeeping: add a `.gitignore` (data/, build/, dist/, `.~lock.*#`). Do not commit `ms_access/.~lock.CSV_Skibazar.csv#`.

## Milestones
1. **M0 Scaffold:** pyproject (uv), FastAPI hello page, ruff, pytest, `.gitignore`.
2. **M1 Core:** `money.py`, `fees.py` and the models plus numbering service, with exhaustive unit tests (rounding edge cases, negative payouts, exemptions, range overlaps).
3. **M2 UI foundation:** the base layout, navigation with step indicator, design system (`app.css`), form components, price input mask, toast/feedback, confirmation dialogs and the print stylesheet.
4. **M2b Setup + CSV import:** settings screens, shop management, and an import with preview, tested against the real `CSV_Skibazar.csv` (41 articles, total 2.545,00 €).
5. **M3 Annahme:** seller entry, fast article entry, A4 seller list print.
6. **M4 Kasse:** checkout, storno, receipt print, concurrency guard against double-selling. Then a **usability click-through** of Annahme and Kasse with 2–3 non-technical volunteers; fix findings before continuing.
7. **M5 Abholung/Abrechnung:** settlement preview, then commit, plus the invoice print.
8. **M6 Übersicht + Audit + Gesamtabrechnung.**
9. **M7 Fallback:** journal, CSV snapshots, SQLite backups, Notfallliste, export.
10. **M8 LAN/phones:** bind option, PINs, responsive polish, QR code.
11. **M9 Packaging + docs:** local PyInstaller builds on Windows and on Linux (build scripts in `packaging/`), German user guide.
12. **M10 Probe-Basar:** a full dry run with volunteers on the target laptop and phones, then a feedback round.

## Verification
- `pytest` covers money parsing and formatting, commission rounding, settlement formulas, numbering and range validation, CSV import (real sample file plus malformed cases), and the full workflow through FastAPI `TestClient`: import shop → register 2 private sellers → sell across sellers → storno → settle all → the Gesamtabrechnung totals reconcile to the cent (Σ sales = Σ payouts + Σ commission + Σ deducted fees).
- UI checks: the price mask and keyboard flow (Enter to advance, focus return) are exercised in a manual checklist on laptop and phone. Error messages are asserted in `TestClient` tests to be plain German text.
- A seed script (`python -m skibasar.demo`) creates a demo basar for manual clicking-through.
- Manual end-to-end: run the PyInstaller exe on Windows and on Linux with no Python installed, open it from a phone over WiFi, print each document type to A4/PDF, then kill the process mid-checkout and confirm the DB, journal and CSV snapshots are consistent after restart.
