import pytest
from fastapi.testclient import TestClient

from skibasar.main import create_app
from skibasar.models import Event, Seller, SellerType


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
    for i, price in enumerate(["10,00", "5,55", "2,25"]):
        c.post(
            f"{url}/artikel",
            data={"expected_number": str(i), "description": f"Ding {i}", "price": price},
        )
    return c


def _sell(client, *numbers):
    return client.post("/kasse/abschluss", data={"cart": list(numbers)}, follow_redirects=False)


def test_search_by_name_article_number_and_shop_range(client):
    with client.app.state.session_factory() as s:
        s.add(
            Seller(
                type=SellerType.shop, name="Krämer", number_range_start=1000, number_range_end=1999
            )
        )
        s.commit()
    assert "Huber" in client.get("/abholung?q=hub").text
    assert "Huber" in client.get("/abholung?q=2").text
    assert "Krämer" not in client.get("/abholung?q=2").text
    assert "Krämer" in client.get("/abholung?q=1500").text
    assert "Keine Verkäufer" in client.get("/abholung?q=zzz").text


def test_preview_is_read_only_and_calculates(client):
    _sell(client, 0, 1)
    page = client.get("/abholung/1").text
    assert "noch nichts gespeichert" in page
    # 15,55 sold; commission 1,555 -> 1,56 (half up); open fee 2,00; payout 12,00 - 0,01
    assert "15,55 €" in page and "1,56 €" in page and "2,00 €" in page and "11,99 €" in page
    with client.app.state.session_factory() as s:
        assert s.get(Seller, 1).settled_at is None
    assert client.get("/abholung/1/rechnung", follow_redirects=False).status_code == 303


def test_finish_marks_returned_and_blocks_sales(client):
    _sell(client, 0)
    r = client.post(
        "/abholung/1/abschluss",
        data={"returned": ["1", "2"], "expected_payout": "700"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/abholung/1/rechnung")
    invoice = client.get("/abholung/1/rechnung").text
    assert "Unterschrift" in invoice and "zurückgegeben" in invoice and "7,00 €" in invoice
    kasse = client.post("/kasse/artikel", data={"number": "1"})
    assert kasse.status_code == 422 and "zurückgegeben" in kasse.text
    again = client.post("/abholung/1/abschluss", data={})
    assert again.status_code == 409 and "schon abgerechnet" in again.text


def test_unticked_articles_stay_available(client):
    client.post("/abholung/1/abschluss", data={"returned": ["1"]}, follow_redirects=False)
    page = client.get("/abholung/1").text
    assert page.count("zurückgegeben") >= 1


def test_negative_payout_shows_seller_pays(client):
    page = client.get("/abholung/1").text
    assert "Verkäufer zahlt" in page and "2,00 €" in page


def test_exempt_seller_pays_nothing(client):
    _sell(client, 0)
    with client.app.state.session_factory() as s:
        s.get(Seller, 1).fee_exempt = True
        s.commit()
    page = client.get("/abholung/1").text
    assert "Auszahlung" in page and "10,00 €" in page


def test_stale_preview_refused(client):
    _sell(client, 0)
    r = client.post("/abholung/1/abschluss", data={"expected_payout": "1"})
    assert r.status_code == 409 and "inzwischen geändert" in r.text
    with client.app.state.session_factory() as s:
        assert s.get(Seller, 1).settled_at is None


def test_unknown_seller_404(client):
    assert client.get("/abholung/99").status_code == 404


def test_invoice_is_frozen_after_settlement(client):
    _sell(client, 0)
    client.post("/abholung/1/abschluss", data={"returned": ["1", "2"]}, follow_redirects=False)
    before = client.get("/abholung/1/rechnung").text
    with client.app.state.session_factory() as s:
        event = s.get(Event, 1)
        event.commission_private_bp = 5000
        event.offer_fee_private_cents = 900
        s.commit()
    assert client.get("/abholung/1/rechnung").text == before
    assert "7,00 €" in before
