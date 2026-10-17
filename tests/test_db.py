import sqlite3

from skibasar.db import init_db, make_engine
from skibasar.models import Event, Sale, Seller


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


def test_upgrade_backfills_sale_items_from_articles_of_valid_sales(tmp_path):
    db = tmp_path / "old.db"
    engine = make_engine(db)
    init_db(engine)
    engine.dispose()
    con = sqlite3.connect(db)
    con.execute("DROP TABLE sale_item")
    con.execute("INSERT INTO sale (id, total_cents, cancelled) VALUES (1, 1500, 0), (2, 700, 1)")
    con.execute(
        "INSERT INTO seller (id, name, type, first_name, phone, email, address, notes,"
        " fee_exempt, offer_fee_paid_at_entry)"
        " VALUES (1, 'S', 'private', '', '', '', '', '', 0, 0)"
    )
    con.execute(
        "INSERT INTO article (number, seller_id, description, brand, size, color, price_cents,"
        " shop_ref, status, sale_id) VALUES (0, 1, 'A', '', '', '', 1000, '', 'sold', 1),"
        " (1, 1, 'B', '', '', '', 500, '', 'sold', 1),"
        " (2, 1, 'C', '', '', '', 700, '', 'available', NULL)"
    )
    con.commit()
    con.close()

    for _ in range(2):  # a second start must not duplicate the items
        with init_db(make_engine(db))() as s:
            sales = {x.id: [(i.number, i.price_cents) for i in x.items] for x in s.query(Sale)}
    assert sales == {1: [(0, 1000), (1, 500)], 2: []}
