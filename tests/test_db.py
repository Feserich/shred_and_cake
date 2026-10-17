import sqlite3

from skibasar.db import init_db, make_engine
from skibasar.models import Event, Seller


def test_upgrade_adds_paid_fee_column_to_old_database(tmp_path):
    db = tmp_path / "old.db"
    engine = make_engine(db)
    init_db(engine)
    engine.dispose()
    # Simulate a database created before offer_fee_paid_cents existed
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE seller DROP COLUMN offer_fee_paid_cents")
    con.execute("UPDATE event SET offer_fee_private_cents = 250, offer_fee_shop_cents = 1000")
    rows = [
        ("Paid", "private", 0, 1),
        ("Open", "private", 0, 0),
        ("Exempt", "private", 1, 1),
        ("Shop", "shop", 0, 1),
    ]
    con.executemany(
        "INSERT INTO seller (name, type, first_name, phone, email, address, notes,"
        " fee_exempt, offer_fee_paid_at_entry) VALUES (?, ?, '', '', '', '', '', ?, ?)",
        rows,
    )
    con.commit()
    con.close()

    with init_db(make_engine(db))() as s:
        paid = {x.name: x.offer_fee_paid_cents for x in s.query(Seller)}
    assert paid == {"Paid": 250, "Open": None, "Exempt": None, "Shop": 1000}


def test_upgrade_adds_admin_pin_column_to_old_database(tmp_path):
    db = tmp_path / "old.db"
    engine = make_engine(db)
    init_db(engine)
    engine.dispose()
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE event DROP COLUMN admin_pin_hash")
    con.commit()
    con.close()

    with init_db(make_engine(db))() as s:
        assert s.get(Event, 1).admin_pin_hash == ""
