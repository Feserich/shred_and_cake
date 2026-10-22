import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from skibasar.main import create_app
from skibasar.models import AuditLog, Event, Expense
from skibasar.services import abschluss


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(tmp_path / "app.db"))
    with c.app.state.session_factory() as s:
        event = s.get(Event, 1)
        event.offer_fee_private_cents = 200
        event.commission_private_bp = 1000
        s.commit()
    r = c.post("/annahme/verkaeufer", data={"name": "Huber"}, follow_redirects=False)
    url = r.headers["location"]
    for n, price in enumerate(["10,00", "20,00"]):
        c.post(
            f"{url}/artikel",
            data={"expected_number": str(n), "description": f"Ding {n}", "price": price},
        )
    return c


def _save(client, **fields):
    data = {"cake_income": "0", "float_1": "0", "float_2": "0", "cash_1": "", "cash_2": ""}
    return client.post("/abschluss", data={**data, **fields}, follow_redirects=False)


def _build(client):
    with client.app.state.session_factory() as s:
        return abschluss.build(s)


def test_page_renders(client):
    r = client.get("/abschluss")
    assert r.status_code == 200
    assert "Gewinn insgesamt" in r.text


def test_profit_of_bazaar_cake_and_overall(client):
    client.post("/kasse/abschluss", data={"cart": ["0", "1"]})
    # Settle the seller: 30,00 sold, 10 % = 3,00 commission, fee 2 x 2,00 deducted
    client.post("/abholung/1/abschluss", data={"expected_payout": "2300"}, follow_redirects=False)
    assert _save(client, cake_income="85,50", float_1="50", float_2="50").status_code == 303
    client.post("/abschluss/ausgaben", data={"description": "Plakate", "amount": "4,00"})
    client.post(
        "/abschluss/ausgaben",
        data={"description": "Zutaten", "amount": "15,50", "category": "cake"},
    )
    r = _build(client)
    assert r.club_income_cents == 700
    assert (r.bazaar_expenses_cents, r.cake_expenses_cents) == (400, 1550)
    assert r.bazaar_profit_cents == 300
    assert r.cake_profit_cents == 7000
    assert r.total_profit_cents == 7300
    assert r.open_sellers == 0


def test_cash_check(client):
    client.post("/kasse/abschluss", data={"cart": ["0", "1"]})
    _save(client, float_1="50", float_2="20", cash_1="130", cash_2="20")
    r = _build(client)
    assert r.expected_cash_cents == 7000 + 3000  # floats + sales, nobody paid out yet
    assert r.cash_difference_cents == 15000 - 10000
    _save(client, float_1="50", float_2="20", cash_1="", cash_2="20")
    assert _build(client).cash_difference_cents is None
    client.post(
        "/abschluss/ausgaben",
        data={"description": "Pizza", "amount": "10", "paid_from_till": "on"},
    )
    assert _build(client).expected_cash_cents == 9000


def test_validation_messages_are_german(client):
    r = _save(client, cake_income="abc")
    assert r.status_code == 422
    assert "kein gültiger Betrag" in r.text
    assert _save(client, float_1="-5").status_code == 422
    r = client.post("/abschluss/ausgaben", data={"description": "", "amount": "5"})
    assert r.status_code == 422 and "wofür" in r.text
    r = client.post("/abschluss/ausgaben", data={"description": "x", "amount": "0"})
    assert r.status_code == 422 and "größer als 0" in r.text
    with client.app.state.session_factory() as s:
        assert s.scalar(select(Expense)) is None


def test_delete_expense_is_audited(client):
    client.post("/abschluss/ausgaben", data={"description": "Plakate", "amount": "4"})
    assert "Plakate" in client.get("/abschluss").text
    assert client.post("/abschluss/ausgaben/1/loeschen", follow_redirects=False).status_code == 303
    assert client.post("/abschluss/ausgaben/1/loeschen").status_code == 404
    with client.app.state.session_factory() as s:
        actions = [
            a.action for a in s.scalars(select(AuditLog).where(AuditLog.entity == "expense"))
        ]
    assert actions == ["create", "delete"]


def test_open_sellers_warning(client):
    assert "noch nicht abgerechnet" in client.get("/abschluss").text
