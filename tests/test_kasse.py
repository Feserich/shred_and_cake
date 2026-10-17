import pytest
from fastapi.testclient import TestClient

from skibasar.main import create_app


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(tmp_path / "app.db"))
    r = c.post("/annahme/verkaeufer", data={"name": "Huber"}, follow_redirects=False)
    url = r.headers["location"]
    for i, price in enumerate(["10,00", "5,50", "2,25"]):
        c.post(
            f"{url}/artikel",
            data={"expected_number": str(i), "description": f"Ding {i}", "price": price},
        )
    c.seller_url = url
    return c


def _add(client, number, cart=()):
    return client.post("/kasse/artikel", data={"number": str(number), "cart": list(cart)})


def _sell(client, *numbers):
    return client.post("/kasse/abschluss", data={"cart": list(numbers)}, follow_redirects=False)


def test_add_shows_line_and_total(client):
    r = _add(client, 0)
    assert r.status_code == 200 and "Ding 0" in r.text and "10,00 €" in r.text
    r = _add(client, 1, cart=[0])
    assert "15,50 €" in r.text and "2 Artikel" in r.text


@pytest.mark.parametrize(
    ("number", "message"),
    [("99", "gibt es nicht"), ("abc", "keine Nummer"), ("", "Artikelnummer eingeben")],
)
def test_bad_numbers_give_german_error(client, number, message):
    r = _add(client, number)
    assert r.status_code == 422 and message in r.text


def test_duplicate_in_cart_rejected(client):
    r = _add(client, 0, cart=[0])
    assert r.status_code == 422 and "schon in diesem Verkauf" in r.text


def test_complete_sale_marks_sold_and_blocks_resale(client):
    r = _sell(client, 0, 1)
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert "15,50 €" in page
    again = _add(client, 0)
    assert again.status_code == 422 and "schon verkauft" in again.text


def test_double_sell_from_stale_cart_is_refused(client):
    assert _sell(client, 0, 1).status_code == 303
    r = _sell(client, 1, 2)  # second device still had 1 in its cart
    assert r.status_code == 409 and "schon verkauft" in r.text
    assert "Noch keine" not in client.get("/kasse/verkaeufe").text  # first sale stays
    assert _add(client, 2).status_code == 200  # 2 was not sold by the failed attempt


def test_empty_sale_refused(client):
    assert _sell(client).status_code == 409


def test_storno_frees_articles(client):
    sale_url = _sell(client, 0, 1).headers["location"]
    sale_id = sale_url.split("/")[-1]
    r = client.post(f"/kasse/verkauf/{sale_id}/storno", follow_redirects=False)
    assert r.status_code == 303
    assert "storniert" in client.get("/kasse/verkaeufe").text
    assert _add(client, 0).status_code == 200
    again = client.post(f"/kasse/verkauf/{sale_id}/storno")
    assert again.status_code == 409 and "schon storniert" in again.text


def test_settled_seller_blocks_sale_and_storno(client, tmp_path):
    sale_id = _sell(client, 0).headers["location"].split("/")[-1]
    from datetime import datetime

    from skibasar.models import Seller

    with client.app.state.session_factory() as s:
        s.get(Seller, 1).settled_at = datetime.now()
        s.commit()
    assert "bereits abgerechnet" in _add(client, 1).text
    r = client.post(f"/kasse/verkauf/{sale_id}/storno")
    assert r.status_code == 409 and "bereits abgerechnet" in r.text


def test_remove_line_and_last(client):
    r = client.post("/kasse/entfernen", data={"cart": ["0", "1", "2"], "remove": "1"})
    assert "Ding 1" not in r.text and "Ding 0" in r.text
    r = client.post("/kasse/entfernen", data={"cart": ["0", "2"], "remove": "last"})
    assert "Ding 2" not in r.text and "Ding 0" in r.text


def test_change_due(client):
    def post(given):
        return client.post("/kasse/rueckgeld", data={"total": "1550", "given": given}).text

    assert "4,50 €" in post("20")
    assert "Es fehlen 0,50 €" in post("15")
    assert "nicht lesbar" in post("abc")
    assert "4,50 €" in post("20.00")
    assert post("") == ""


def test_receipt_and_list(client):
    sale_id = _sell(client, 0, 2).headers["location"].split("/")[-1]
    receipt = client.get(f"/kasse/verkauf/{sale_id}/beleg").text
    assert "Ding 0" in receipt and "12,25 €" in receipt
    assert client.get("/kasse/verkauf/999").status_code == 404
