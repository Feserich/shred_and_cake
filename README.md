# sce_skibasar

Offline web application for the Ski Basar of our ski club. It replaces the old MS Access program
(CasaBazar20) with a modern, easy-to-use solution that runs on a single laptop, with optional
access from phones over the local WiFi.

The user interface and printouts are in German; code and comments are in English.
The end-user manual (German) is in [docs/Anleitung.md](docs/Anleitung.md).

## Workflow of the Basar

1. **Pre-Basar:** Shops send a CSV file with their equipment and prices. Every article is
   pre-labeled with a price tag and an article number. Each shop has a fixed number range
   (e.g. 1000–1999).
2. **Annahme (morning):** Individual sellers register and hand in their articles. The system
   assigns the next free article number; the volunteer sticks the matching pre-printed tag on the
   article. Each seller gets a printout of their articles and prices.
3. **Kasse (noon):** Buyers bring their articles to the checkout. The system sums them up and marks
   them as sold. A receipt can optionally be printed.
4. **Abholung (afternoon):** Sellers and shops pick up unsold articles and their payout. Offer fee
   and commission (different for shops and individuals) are deducted; an invoice is printed.
5. **Übersicht / Gesamtabrechnung:** Tables for sellers, articles and sales allow manual
   corrections at any time (every change is logged); the overall settlement shows totals for the
   whole Basar.

## Features

- Server-rendered FastAPI app (Jinja2, HTMX/Alpine.js vendored, no CDN) – works fully offline.
- All money is stored and calculated as integer **cents**, so there are no rounding errors.
- CSV import of shop lists (Latin-1, German number format) with preview and diff on re-import.
- **Fallback if the software fails:** every change is written to `data/journal.csv`; periodic
  snapshots and backups are kept; an emergency article list can be printed so the Basar can go on
  on paper.
- Phones in the local WiFi (`--lan`) get access via QR code and event PIN; the laptop needs no PIN.
  An optional admin PIN guards edits of already settled sellers.
- Pre-built executables for Windows and Linux (PyInstaller).

## Requirements

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/) for development.
- No installation needed for the packaged executables.

## Development

```bash
uv sync                     # install dependencies (including dev group)
uv run skibasar             # start the server, opens http://localhost:8000
uv run skibasar --lan       # additionally allow phones in the local network
uv run pytest               # run the tests
uv run ruff check .         # lint
```

Command line options: `--lan`, `--port <n>` (default 8000), `--no-browser`.

### Configuration (environment variables)

| Variable | Meaning |
|---|---|
| `SKIBASAR_DATA_DIR` | Folder for database, journal and backups (default: `data/`, next to the exe when packaged) |
| `SKIBASAR_EVENT_PIN` | Fixed PIN for phones (otherwise a random one is generated with `--lan`) |
| `SKIBASAR_ADMIN_PIN` | Admin PIN; overrides the PIN set on the Einstellungen page |

## Building the executables

Builds must be done on the target OS with the same spec file:

```bash
./packaging/build.sh        # Linux   -> dist/skibasar
./packaging/build.ps1       # Windows -> dist/skibasar.exe
```

## Project layout

```
src/skibasar/
  main.py, config.py, db.py, models.py   app factory, settings, database
  money.py, fees.py                      cent-based money handling and fee rules
  csv_import.py, backup.py, network.py   shop CSV import, journal/snapshots, LAN URL + QR code
  routers/                               HTTP endpoints per step (annahme, kasse, abholung, ...)
  services/                              business logic behind the routers
  templates/, static/                    Jinja2 templates, CSS and vendored JS
tests/                                   pytest suite
packaging/                               PyInstaller spec and build scripts
docs/                                    German manual and implementation plan
```

See [docs/implementation_plan.md](docs/implementation_plan.md) for the design decisions and
architecture.
