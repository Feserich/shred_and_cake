import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from skibasar.main import create_app
from skibasar.models import Article, AuditLog, Event, Expense, Seller
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
    data = {"float_1": "0", "float_2": "0", "cash_1": "", "cash_2": ""}
    return client.post("/abschluss", data={**data, **fields}, follow_redirects=False)


def _build(client):
    with client.app.state.session_factory() as s:
        return abschluss.build(s)


def test_page_renders(client):
    r = client.get("/abschluss")
    assert r.status_code == 200
    assert "Basar-Kasse" in r.text and "Kuchen-Kasse" in r.text
    assert "Kuchen-Kasse noch nicht gezählt" in r.text
    _save(client, cash_2="0")
    assert "Gewinn insgesamt" in client.get("/abschluss").text


def test_profit_of_bazaar_cake_and_overall(client):
    client.post("/kasse/abschluss", data={"cart": ["0", "1"]})
    # Settle the seller: 30,00 sold, 10 % = 3,00 commission, fee 2 x 2,00 deducted
    client.post("/abholung/1/abschluss", data={"expected_payout": "2300"}, follow_redirects=False)
    # Cake till: 50,00 change money, 125,50 counted, 10,00 of ingredients paid out of it
    assert _save(client, float_1="50", float_2="50", cash_2="125,50").status_code == 303
    client.post("/abschluss/ausgaben", data={"description": "Plakate", "amount": "4,00"})
    client.post(
        "/abschluss/ausgaben",
        data={"description": "Zutaten", "amount": "15,50", "category": "cake"},
    )
    client.post(
        "/abschluss/ausgaben",
        data={"description": "Milch", "amount": "10", "category": "cake", "paid_from_till": "on"},
    )
    r = _build(client)
    assert r.club_income_cents == 700
    assert (r.bazaar_expenses_cents, r.cake_expenses_cents) == (400, 2550)
    assert r.bazaar_profit_cents == 300
    assert r.cake_income_cents == 12550 - 5000 + 1000
    assert r.cake_profit_cents == 8550 - 2550
    assert r.total_profit_cents == 300 + 6000
    assert r.open_sellers == 0
    assert "Gewinn Kuchenverkauf" in client.get("/abschluss").text


def test_cake_profit_unknown_until_the_cake_till_is_counted(client):
    _save(client, float_2="50")
    r = _build(client)
    assert r.cake_income_cents is r.cake_profit_cents is r.total_profit_cents is None
    assert "Fehlt noch: Kuchen-Kasse zählen" in client.get("/abschluss").text


def test_cash_check_of_the_bazaar_till(client):
    client.post("/kasse/abschluss", data={"cart": ["0", "1"]})
    _save(client, float_1="50", float_2="20", cash_1="130", cash_2="20")
    r = _build(client)
    # Only the Basar till: change money + sales, nobody paid out yet; the cake till is separate
    assert r.expected_cash_cents == 5000 + 3000
    assert r.cash_difference_cents == 13000 - 8000
    _save(client, float_1="50", float_2="20", cash_1="", cash_2="20")
    assert _build(client).cash_difference_cents is None
    client.post(
        "/abschluss/ausgaben",
        data={"description": "Pizza", "amount": "10", "paid_from_till": "on"},
    )
    assert _build(client).expected_cash_cents == 7000
    # A cake expense paid from the cake till does not touch the Basar till
    client.post(
        "/abschluss/ausgaben",
        data={"description": "Mehl", "amount": "5", "category": "cake", "paid_from_till": "on"},
    )
    assert _build(client).expected_cash_cents == 7000


def test_validation_messages_are_german(client):
    r = _save(client, cash_2="abc")
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


def test_full_day_cash_check_balances_to_the_cent(client):
    with client.app.state.session_factory() as s:
        event = s.get(Event, 1)
        event.offer_fee_shop_cents = 2500
        event.commission_shop_bp = 500
        s.commit()
    # Huber (fixture: 0 = 10,00, 1 = 20,00) pays 2 x 2,00 at entry
    client.post("/annahme/1/gebuehr")
    # Teacher: no offer fee, but commission
    client.post("/annahme/verkaeufer", data={"name": "Lehrer", "fee_exempt": "on"})
    client.post(
        "/annahme/2/artikel", data={"expected_number": "2", "description": "Ski", "price": "30"}
    )
    # Maier sells nothing and owes the club 2 x 2,00
    client.post("/annahme/verkaeufer", data={"name": "Maier"})
    for n, price in ((3, "15"), (4, "7,50")):
        client.post(
            "/annahme/3/artikel",
            data={"expected_number": str(n), "description": "x", "price": price},
        )
    # Shop pays its 25,00 fee at entry
    shop = {
        "name": "Sport",
        "range_start": "1000",
        "range_end": "1999",
        "offer_fee_paid_at_entry": "on",
    }
    client.post("/haendler", data=shop)
    with client.app.state.session_factory() as s:
        s.add(Article(number=1000, seller_id=4, description="Board", price_cents=10000))
        s.commit()

    client.post("/kasse/abschluss", data={"cart": ["0", "1000"]})
    client.post("/kasse/abschluss", data={"cart": ["2"]})
    storno = client.post("/kasse/abschluss", data={"cart": ["4"]}, follow_redirects=False)
    client.post(storno.headers["location"].split("?")[0] + "/storno")
    for seller_id in (1, 2, 3, 4):
        client.post(f"/abholung/{seller_id}/abschluss", data={"returned": []})
    with client.app.state.session_factory() as s:
        payouts = [s.get(Seller, i).settled_payout_cents for i in (1, 2, 3, 4)]
    # Huber 10,00 - 1,00; teacher 30,00 - 3,00; Maier -4,00 fee; shop 100,00 - 5 %
    assert payouts == [900, 2700, -400, 9500]

    client.post(
        "/abschluss/ausgaben", data={"description": "Pizza", "amount": "10", "paid_from_till": "on"}
    )
    _save(client, float_1="100", cash_1="132")
    r = _build(client)
    assert r.open_sellers == 0 and r.reconciles
    # commission 1 + 3 + 0 + 5, fees at entry 4 + 25, deducted fee 4
    assert r.club_income_cents == 900 + 2900 + 400
    # change money 100 + sales 140 + fees at entry 29 - payouts 127 - till expense 10
    assert r.expected_cash_cents == 13200
    assert r.cash_difference_cents == 0
    # With everyone settled, the cash the Basar brought in is exactly the club income
    assert r.expected_cash_cents - r.float_cents + 1000 == r.club_income_cents
