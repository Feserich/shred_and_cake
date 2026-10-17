"""Database engine and session handling (SQLite, WAL mode)."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Event


def make_engine(db_path: Path | str) -> Engine:
    url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def _upgrade(engine: Engine) -> None:
    """Add columns introduced after a database was created (create_all never alters tables)."""
    event_columns = {c["name"] for c in inspect(engine).get_columns("event")}
    if "admin_pin_hash" not in event_columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE event ADD COLUMN admin_pin_hash VARCHAR(200) DEFAULT ''")
            )
    columns = {c["name"] for c in inspect(engine).get_columns("seller")}
    if "offer_fee_paid_cents" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE seller ADD COLUMN offer_fee_paid_cents INTEGER"))
            # Best guess for fees paid before this column existed: the current setting
            conn.execute(
                text(
                    "UPDATE seller SET offer_fee_paid_cents = (SELECT CASE seller.type"
                    " WHEN 'shop' THEN offer_fee_shop_cents ELSE offer_fee_private_cents END"
                    " FROM event WHERE event.id = 1)"
                    " WHERE offer_fee_paid_at_entry AND NOT fee_exempt"
                )
            )


def _backfill_sale_items(engine: Engine) -> None:
    """Items for sales made before sale_item existed; cancelled ones have lost their articles."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sale_item (sale_id, article_id, number, description, price_cents)"
                " SELECT sale_id, id, number, description, price_cents FROM article"
                " WHERE sale_id IS NOT NULL"
                " AND NOT EXISTS"
                " (SELECT 1 FROM sale_item WHERE sale_item.sale_id = article.sale_id)"
            )
        )


def init_db(engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(engine)
    _upgrade(engine)
    _backfill_sale_items(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        if s.get(Event, 1) is None:
            s.add(Event(id=1))
            s.commit()
    return factory


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as s:
        yield s
