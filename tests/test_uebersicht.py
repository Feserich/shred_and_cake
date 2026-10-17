import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from skibasar.main import create_app
from skibasar.models import Article, ArticleStatus, AuditLog, Event, Seller
from skibasar.services import reports


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(tmp_path / "app.db"))
    with c.app.state.session_factory() as s:
        event = s.get(Event, 1)
        event.offer_fee_private_cents = 200
        event.commission_private_bp = 1000
        s.commit()
    for name, prices in (("Huber", ["10,00", "5,55", "2,25"]), ("Maier", ["20,00", "7,00"])):
        r = c.post("/annahme/verkaeufer", data={"name": name}, follow_redirects=False)
        url = r.headers["location"]
        for price in prices:
            with c.app.state.session_factory() as s:
                nxt = len(list(s.scalars(select(Article))))
            c.post(
                f"{url}/artikel",
                data={"expected_number": str(nxt), "description": f"Ding {nxt}", "price": price},
            )
    return c


def _sell(client, *numbers):
    return client.post("/kasse/abschluss", data={"cart": list(numbers)}, follow_redirects=False)


def _audit(client):
    with client.app.state.session_factory() as s:
        return list(s.scalars(select(AuditLog).order_by(AuditLog.id)))


def test_tables_search_and_filter(client):
    assert "Huber" in client.get("/uebersicht/verkaeufer?q=hub").text
    assert "Maier" not in client.get("/uebersicht/verkaeufer?q=hub").text
    assert "Maier" in client.get("/uebersicht/verkaeufer?q=4").text  # article number 4
    assert "Ding 3" in client.get("/uebersicht/artikel?q=Maier").text
    assert "Ding 0" not in client.get("/uebersicht/artikel?q=Maier").text
    _sell(client, 0)
    assert "Ding 0" in client.get("/uebersicht/artikel?status=sold").text
    assert "Ding 1" not in client.get("/uebersicht/artikel?status=sold").text
    assert "Verkäufe" in client.get("/uebersicht/verkaeufe").text
    assert client.get("/uebersicht", follow_redirects=False).status_code == 303


def test_edit_article_is_audited(client):
    r = client.post(
        "/uebersicht/artikel/1",
        data={"description": "Skihose", "price": "8", "status": "withdrawn"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with client.app.state.session_factory() as s:
        a = s.scalar(select(Article).where(Article.number == 1))
        assert (a.description, a.price_cents, a.status) == ("Skihose", 800, ArticleStatus.withdrawn)
    entry = _audit(client)[-1]
    assert (entry.entity, entry.action) == ("article", "update")
    assert "Ding 1" in entry.before and "Skihose" in entry.after
    page = client.get("/uebersicht/protokoll").text
    assert "Skihose" in page and "geändert" in page


def test_sold_article_keeps_price_and_status(client):
    _sell(client, 0)
    r = client.post(
        "/uebersicht/artikel/0",
        data={"description": "Ding 0", "price": "1", "status": "sold"},
    )
    assert r.status_code == 422 and "stornieren" in r.text
    r = client.post(
        "/uebersicht/artikel/0",
        data={"description": "Ding 0", "price": "10,00", "status": "available"},
    )
    assert r.status_code == 422
    r = client.post(
        "/uebersicht/artikel/0",
        data={"description": "Neu", "price": "10,00", "status": "sold"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_edit_validation_messages_are_german(client):
    bad = {"description": "x", "price": "abc", "status": "available"}
    r = client.post("/uebersicht/artikel/1", data=bad)
    assert r.status_code == 422 and "Preis ist nicht lesbar" in r.text
    r = client.post("/uebersicht/verkaeufer/1", data={"name": " "})
    assert r.status_code == 422 and "Name fehlt" in r.text


def test_settled_seller_needs_admin_pin(client, monkeypatch):
    _sell(client, 0)
    client.post("/abholung/1/abschluss", data={"returned": ["1", "2"], "expected_payout": "700"})
    form = {"name": "Huber-Neu", "phone": "123"}
    monkeypatch.delenv("SKIBASAR_ADMIN_PIN", raising=False)
    r = client.post("/uebersicht/verkaeufer/1", data=form)
    assert r.status_code == 422 and "noch keine eingerichtet" in r.text
    monkeypatch.setenv("SKIBASAR_ADMIN_PIN", "4711")
    r = client.post("/uebersicht/verkaeufer/1", data=form | {"admin_pin": "0000"})
    assert r.status_code == 422 and "PIN ist falsch" in r.text
    r = client.post(
        "/uebersicht/verkaeufer/1", data=form | {"admin_pin": "4711"}, follow_redirects=False
    )
    assert r.status_code == 303
    with client.app.state.session_factory() as s:
        seller = s.get(Seller, 1)
        assert seller.name == "Huber-Neu" and seller.settled_payout_cents == 700
    # price/status of an article of a settled seller stay locked even with the PIN
    r = client.post(
        "/uebersicht/artikel/1",
        data={"description": "x", "price": "99", "status": "available", "admin_pin": "4711"},
    )
    assert r.status_code == 422


def test_fee_paid_at_entry_survives_fee_change(client):
    # Huber pays 2,00 € in cash; then the fee setting is raised to 5,00 €
    client.post("/uebersicht/verkaeufer/1", data={"name": "Huber", "offer_fee_paid_at_entry": "on"})
    settings = {"name": "B", "offer_fee_private": "5,00", "commission_private": "10"}
    client.post("/einstellungen", data=settings)
    with client.app.state.session_factory() as s:
        assert reports.build(s).fee_at_entry_cents == 200
    assert "2,00 € bezahlt" in client.get("/annahme/1/liste").text
    # Saving the seller again keeps the recorded amount; a newly paying seller pays the new fee
    client.post("/uebersicht/verkaeufer/1", data={"name": "Huber", "offer_fee_paid_at_entry": "on"})
    client.post("/uebersicht/verkaeufer/2", data={"name": "Maier", "offer_fee_paid_at_entry": "on"})
    with client.app.state.session_factory() as s:
        assert reports.build(s).fee_at_entry_cents == 200 + 500
    _sell(client, 0)
    client.post("/abholung/1/abschluss", data={"expected_payout": "900"})
    invoice = client.get("/abholung/1/rechnung").text
    assert "Angebotsgebühr 2,00 € bei der Annahme bezahlt" in invoice
    # Unticking "paid" forgets the amount: the fee is open again
    client.post("/uebersicht/verkaeufer/2", data={"name": "Maier"})
    with client.app.state.session_factory() as s:
        assert s.get(Seller, 2).offer_fee_paid_cents is None


def test_gesamtabrechnung_reconciles_to_the_cent(client):
    # Huber 0,1,2 / Maier 3,4; seller 1 pays the fee at entry
    client.post("/uebersicht/verkaeufer/2", data={"name": "Maier", "offer_fee_paid_at_entry": "on"})
    _sell(client, 0, 1)
    _sell(client, 3)
    _sell(client, 2)
    sale = client.post("/kasse/abschluss", data={"cart": ["4"]}, follow_redirects=False)
    sale_url = sale.headers["location"].split("?")[0]
    client.post(f"{sale_url}/storno")
    page = client.get("/gesamtabrechnung").text
    assert "Die Zahlen stimmen" in page
    assert "Stornierte Verkäufe" in page and "Alle Verkäufer sind abgerechnet" not in page

    client.post("/abholung/1/abschluss", data={"returned": [], "expected_payout": "1402"})
    page = client.get("/gesamtabrechnung").text
    # Huber sold 10,00 + 5,55 + 2,25 = 17,80; commission 1,78; fee 2,00 -> 14,02
    assert "17,80 €" in page and "1,78 €" in page and "14,02 €" in page
    assert "Die Zahlen stimmen" in page

    client.post("/abholung/2/abschluss", data={"returned": ["4"]})
    page = client.get("/gesamtabrechnung").text
    assert "Alle Verkäufer sind abgerechnet" in page and "Die Zahlen stimmen" in page
    with client.app.state.session_factory() as s:
        sellers = list(s.scalars(select(Seller)))
        sold = sum(s_.settled_sold_total_cents for s_ in sellers)
        parts = sum(
            s_.settled_payout_cents + s_.settled_commission_cents + s_.settled_open_fee_cents
            for s_ in sellers
        )
        assert sold == parts == 1780 + 2000


def test_high_price_edit_needs_confirmation(client):
    data = {"description": "Ding 1", "price": "1.500", "status": "available"}
    r = client.post("/uebersicht/artikel/1", data=data, follow_redirects=False)
    assert r.status_code == 200 and "Preis stimmt" in r.text
    with client.app.state.session_factory() as s:
        assert s.scalar(select(Article).where(Article.number == 1)).price_cents != 150000
    r = client.post("/uebersicht/artikel/1", data={**data, "price_ok": "1"}, follow_redirects=False)
    assert r.status_code == 303
    with client.app.state.session_factory() as s:
        assert s.scalar(select(Article).where(Article.number == 1)).price_cents == 150000
