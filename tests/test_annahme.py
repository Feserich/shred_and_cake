import pytest
from fastapi.testclient import TestClient

from skibasar.main import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "app.db"))


def _seller(client, **extra):
    r = client.post(
        "/annahme/verkaeufer",
        data={"name": "Huber", "first_name": "Anna", **extra},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return r.headers["location"]


def _article(client, url, number, price="12,50", desc="Skijacke"):
    return client.post(
        f"{url}/artikel",
        data={"expected_number": str(number), "description": desc, "price": price},
        follow_redirects=False,
    )


def test_seller_requires_name(client):
    r = client.post("/annahme/verkaeufer", data={"name": " "})
    assert r.status_code == 422 and "Name fehlt" in r.text


def test_article_entry_numbers_sequentially(client):
    url = _seller(client)
    assert "<strong>0</strong>" in client.get(url).text
    assert _article(client, url, 0).status_code == 303
    assert _article(client, url, 1, price="400,00").status_code == 303
    page = client.get(url).text
    assert "<strong>2</strong>" in page and "400,00 €" in page and "Summe 412,50 €" in page


def test_stale_expected_number_is_rejected(client):
    url = _seller(client)
    _article(client, url, 0)
    r = _article(client, url, 0)
    assert r.status_code == 422 and "inzwischen vergeben" in r.text
    assert client.get(url).text.count("Skijacke") == 1


def test_invalid_price_keeps_input(client):
    url = _seller(client)
    r = _article(client, url, 0, price="1,2,3", desc="Helm")
    assert r.status_code == 422 and "kein gültiger Betrag" in r.text and 'value="Helm"' in r.text
    assert _article(client, url, 0, price="0").status_code == 422


def test_price_with_decimal_point_is_accepted(client):
    # Enter in the price field submits before the client-side mask turns "." into ","
    url = _seller(client)
    assert _article(client, url, 0, price="12.50").status_code == 303
    assert "12,50 €" in client.get(url).text


def test_numbers_are_shared_across_sellers_and_skip_shop_ranges(client):
    client.post("/haendler", data={"name": "Shop", "range_start": "2", "range_end": "4"})
    a, b = _seller(client), _seller(client)
    _article(client, a, 0)
    _article(client, b, 1)
    assert "<strong>5</strong>" in client.get(a).text


def test_fee_status_and_print_list(client):
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "2,50"})
    open_fee = _seller(client)
    paid = _seller(client, offer_fee_paid_at_entry="on")
    exempt = _seller(client, fee_exempt="on", offer_fee_paid_at_entry="on")
    _article(client, open_fee, 0)
    assert "2,50 € offen" in client.get(f"{open_fee}/liste").text
    assert "2,50 € bezahlt" in client.get(f"{paid}/liste").text
    page = client.get(f"{exempt}/liste").text
    assert "Gebührenfrei" in page and "Unterschrift" in page
    assert "Skijacke" in client.get(f"{open_fee}/liste").text


def test_search_by_name_and_article_number(client):
    url = _seller(client)
    _article(client, url, 0)
    assert "Huber" in client.get("/annahme?q=hub").text
    assert "Huber" in client.get("/annahme?q=0").text
    assert "Keine Verkäufer" in client.get("/annahme?q=7").text


def test_update_seller_and_unknown_seller(client):
    url = _seller(client)
    r = client.post(
        url, data={"name": "Maier", "offer_fee_paid_at_entry": "on"}, follow_redirects=True
    )
    assert "Maier" in r.text and "bezahlt" in r.text
    assert client.get("/annahme/999").status_code == 404


def test_vendored_assets_are_served_offline(client):
    for name in ("htmx.min.js", "alpine.min.js", "pico.min.css", "app.css", "app.js"):
        assert client.get(f"/static/{name}").status_code == 200
    page = client.get("/annahme").text
    assert "http://" not in page and "https://" not in page


def test_entry_form_has_price_mask_and_suggestions(client):
    url = _seller(client)
    client.post(
        f"{url}/artikel",
        data={"expected_number": "0", "description": "Jacke", "brand": "Atomic", "price": "5"},
    )
    page = client.get(url).text
    assert "data-price" in page and "data-enter-advance" in page
    assert '<option value="Atomic">' in page


def test_save_shows_toast_and_undo_removes_last_article(client):
    url = _seller(client)
    _article(client, url, 0)
    page = client.get(f"{url}?saved=1").text
    assert 'data-toast="ok"' in page and "Letzten Artikel zurücknehmen" in page
    r = client.post(f"{url}/artikel/zurueck", follow_redirects=False)
    assert r.status_code == 303
    page = client.get(url).text
    assert "<strong>0</strong>" in page and "Skijacke" not in page
    assert "Letzten Artikel zurücknehmen" not in page
    assert client.post(f"{url}/artikel/zurueck").status_code == 422


def test_undo_only_for_newest_number(client):
    a = _seller(client)
    b = _seller(client)
    _article(client, a, 0)
    _article(client, b, 1)
    assert "Letzten Artikel zurücknehmen" not in client.get(a).text
    assert client.post(f"{a}/artikel/zurueck").status_code == 422


def test_high_price_needs_confirmation(client):
    url = _seller(client)
    r = _article(client, url, 0, price="1.500")
    assert r.status_code == 200 and "Preis stimmt" in r.text and "1.500,00 €" in r.text
    assert "Skijacke" not in client.get(url).text.split("<h2>Artikel")[1].split("<h2>Stammdaten")[0]
    r = client.post(
        f"{url}/artikel",
        data={"expected_number": "0", "description": "Skijacke", "price": "1.500", "price_ok": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "1.500,00 €" in client.get(url).text


def test_price_at_limit_saves_directly(client):
    assert _article(client, _seller(client), 0, price="500,00").status_code == 303


def test_fee_checkbox_shows_amount(client):
    client.post(
        "/einstellungen",
        data={
            "name": "x",
            "event_date": "2026-11-07",
            "private_number_start": "0",
            "offer_fee_private": "2,00",
            "commission_private": "10",
            "offer_fee_shop": "0",
            "commission_shop": "7,5",
        },
    )
    assert "Gebühr bezahlt (2,00 €)" in client.get("/annahme").text
    url = _seller(client)
    assert "Gebühr bezahlt (2,00 €)" in client.get(url).text
