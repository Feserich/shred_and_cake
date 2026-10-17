"""Fallback & data safety: append-only journal, CSV snapshots, SQLite backups, export."""

import csv
import io
import os
import sqlite3
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Article, AuditLog, Sale, Seller
from .money import format_eur

JOURNAL_HEADER = ["Zeit", "Nr", "Gerät", "Objekt", "Objekt-ID", "Aktion", "Vorher", "Nachher"]
KEEP_BACKUPS = 20
SNAPSHOT_FILES = ("sellers.csv", "articles.csv", "sales.csv")


def _write_csv(path: Path, header: list[str], rows) -> None:
    """Atomically write a ';'-separated UTF-8-with-BOM CSV (opens cleanly in German Excel)."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _money(cents: int | None) -> list[str]:
    return ["", ""] if cents is None else [str(cents), format_eur(cents, symbol=False)]


class Backup:
    """Owns the data directory layout: journal.csv, snapshots, backups/."""

    def __init__(self, db_path: Path | str, factory: sessionmaker[Session]):
        self.db_path = Path(db_path)
        self.dir = self.db_path.parent
        self.journal_path = self.dir / "journal.csv"
        self.snapshot_dir = self.dir / "snapshots"
        self.backup_dir = self.dir / "backups"
        self.factory = factory
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # -- journal ---------------------------------------------------------
    def append_journal(self, entries: list[AuditLog]) -> None:
        if not entries:
            return
        now = datetime.now().isoformat(timespec="seconds")
        buf = io.StringIO(newline="")
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        for e in entries:
            w.writerow(
                [now, e.id, e.client, e.entity, e.entity_id or "", e.action, e.before, e.after]
            )
        with self._lock:
            new = not self.journal_path.exists() or self.journal_path.stat().st_size == 0
            with open(self.journal_path, "a", encoding="utf-8", newline="") as f:
                if new:
                    f.write("\ufeff")
                    head = io.StringIO(newline="")
                    csv.writer(head, delimiter=";", lineterminator="\r\n").writerow(JOURNAL_HEADER)
                    f.write(head.getvalue())
                f.write(buf.getvalue())
                f.flush()
                os.fsync(f.fileno())

    def journal_lines(self) -> int:
        if not self.journal_path.exists():
            return 0
        with open(self.journal_path, encoding="utf-8-sig", newline="") as f:
            return max(sum(1 for _ in csv.reader(f, delimiter=";")) - 1, 0)

    def install(self) -> None:
        """Mirror every committed audit-log entry into the journal (fsynced)."""

        @event.listens_for(self.factory, "after_flush")
        def _collect(session, _ctx):
            pending = session.info.setdefault("journal", [])
            pending.extend(o for o in session.new if isinstance(o, AuditLog))

        @event.listens_for(self.factory, "after_commit")
        def _write(session):
            entries = session.info.pop("journal", [])
            self.append_journal(entries)
            if any(e.action == "settle" for e in entries):
                self.snapshot()

        @event.listens_for(self.factory, "after_rollback")
        def _drop(session):
            session.info.pop("journal", None)

    # -- snapshots -------------------------------------------------------
    def snapshot(self) -> Path:
        with self.factory() as s:
            sellers = [
                [
                    x.id,
                    x.type.value,
                    x.name,
                    x.first_name,
                    x.phone,
                    x.email,
                    x.address,
                    x.number_range_start if x.number_range_start is not None else "",
                    x.number_range_end if x.number_range_end is not None else "",
                    int(x.fee_exempt),
                    int(x.offer_fee_paid_at_entry),
                    *_money(x.offer_fee_paid_cents),
                    x.settled_at.isoformat(sep=" ", timespec="seconds") if x.settled_at else "",
                    *_money(x.settled_sold_total_cents),
                    *_money(x.settled_commission_cents),
                    *_money(x.settled_open_fee_cents),
                    *_money(x.settled_payout_cents),
                    x.notes,
                ]
                for x in s.scalars(select(Seller).order_by(Seller.id))
            ]
            articles = [
                [
                    a.number,
                    a.seller_id,
                    a.description,
                    a.brand,
                    a.size,
                    a.color,
                    *_money(a.price_cents),
                    a.shop_ref,
                    a.status.value,
                    a.sale_id or "",
                ]
                for a in s.scalars(select(Article).order_by(Article.number))
            ]
            sales = [
                [
                    x.id,
                    x.created_at.isoformat(sep=" ", timespec="seconds") if x.created_at else "",
                    *_money(x.total_cents),
                    int(x.cancelled),
                    " ".join(str(i.number) for i in x.items),
                ]
                for x in s.scalars(select(Sale).order_by(Sale.id))
            ]
        _write_csv(
            self.snapshot_dir / "sellers.csv",
            [
                "ID",
                "Typ",
                "Name",
                "Vorname",
                "Telefon",
                "E-Mail",
                "Adresse",
                "Nr von",
                "Nr bis",
                "Gebührenfrei",
                "Gebühr bei Annahme bezahlt",
                "Bezahlte Gebühr Cent",
                "Bezahlte Gebühr",
                "Abgerechnet am",
                "Verkauft Cent",
                "Verkauft",
                "Provision Cent",
                "Provision",
                "Offene Gebühr Cent",
                "Offene Gebühr",
                "Auszahlung Cent",
                "Auszahlung",
                "Notizen",
            ],
            sellers,
        )
        _write_csv(
            self.snapshot_dir / "articles.csv",
            [
                "Nummer",
                "Verkäufer-ID",
                "Bezeichnung",
                "Marke",
                "Größe",
                "Farbe",
                "Preis Cent",
                "Preis",
                "Händler-Nr",
                "Status",
                "Verkauf-ID",
            ],
            articles,
        )
        _write_csv(
            self.snapshot_dir / "sales.csv",
            ["ID", "Zeit", "Summe Cent", "Summe", "Storniert", "Artikel"],
            sales,
        )
        return self.snapshot_dir

    def last_snapshot(self) -> datetime | None:
        files = [self.snapshot_dir / n for n in SNAPSHOT_FILES if (self.snapshot_dir / n).exists()]
        return datetime.fromtimestamp(min(f.stat().st_mtime for f in files)) if files else None

    # -- sqlite backups --------------------------------------------------
    def sqlite_backup(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.backup_dir / f"skibasar-{stamp}.db"
        n = 1
        while target.exists():
            target = self.backup_dir / f"skibasar-{stamp}-{n}.db"
            n += 1
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        for old in self.list_backups()[KEEP_BACKUPS:]:
            old.unlink(missing_ok=True)
        return target

    def list_backups(self) -> list[Path]:
        """Newest first."""
        return sorted(self.backup_dir.glob("skibasar-*.db"), reverse=True)

    def run_all(self) -> Path:
        self.snapshot()
        return self.sqlite_backup()

    # -- export ----------------------------------------------------------
    def export_to(self, folder: Path | str) -> Path:
        """Copy a fresh backup, the snapshots and the journal into ``folder`` (e.g. a USB stick)."""
        target = Path(folder) / f"skibasar-export-{datetime.now():%Y%m%d-%H%M%S}"
        target.mkdir(parents=True, exist_ok=False)
        db = self.run_all()
        (target / db.name).write_bytes(db.read_bytes())
        for name in SNAPSHOT_FILES:
            (target / name).write_bytes((self.snapshot_dir / name).read_bytes())
        if self.journal_path.exists():
            (target / "journal.csv").write_bytes(self.journal_path.read_bytes())
        return target

    def export_zip(self) -> bytes:
        db = self.run_all()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db, db.name)
            for name in SNAPSHOT_FILES:
                z.write(self.snapshot_dir / name, name)
            if self.journal_path.exists():
                z.write(self.journal_path, "journal.csv")
        return buf.getvalue()

    # -- periodic --------------------------------------------------------
    def start(self, interval_s: float = 300) -> None:
        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.run_all()
                except Exception:  # noqa: BLE001 - a failed backup must never kill the app
                    pass

        self._thread = threading.Thread(target=loop, name="skibasar-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
