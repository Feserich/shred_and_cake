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
    paid = _seller(client)
    exempt = _seller(client, fee_exempt="on")
    _article(client, open_fee, 0)
    _article(client, paid, 1)
    client.post(f"{paid}/gebuehr")
    assert "2,50 € offen" in client.get(f"{open_fee}/liste").text
    assert "2,50 € bezahlt" in client.get(f"{paid}/liste").text
    page = client.get(f"{exempt}/liste").text
    assert "Keine Angebotsgebühr" in page and "Unterschrift" in page
    assert "Skijacke" in client.get(f"{open_fee}/liste").text


def test_search_by_name_and_article_number(client):
    url = _seller(client)
    _article(client, url, 0)
    assert "Huber" in client.get("/annahme?q=hub").text
    assert "Huber" in client.get("/annahme?q=0").text
    assert "Keine Verkäufer" in client.get("/annahme?q=7").text


def test_update_seller_and_unknown_seller(client):
    url = _seller(client)
    _article(client, url, 0)
    client.post(f"{url}/gebuehr")
    r = client.post(url, data={"name": "Maier"}, follow_redirects=True)
    assert "Maier" in r.text and "bezahlt" in r.text  # editing the data keeps the payment
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


def test_collect_fee_in_annahme(client):
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "2,50"})
    url = _seller(client)
    _article(client, url, 0)
    _article(client, url, 1)
    page = client.get(url).text
    assert "5,00 €" in page and "Gebühr 5,00 € kassiert" in page
    assert page.index("Summe") < page.index("fee-box") < page.index("Stammdaten")
    assert "offer_fee_paid_at_entry" not in page
    assert client.post(f"{url}/gebuehr", follow_redirects=False).status_code == 303
    page = client.get(url).text
    assert "für alle 2 Artikel bezahlt" in page
    assert client.post(f"{url}/gebuehr").status_code == 422
    _article(client, url, 2)  # a later article is not covered by the earlier payment
    page = client.get(url).text
    assert "Gebühr 2,50 € kassiert" in page
    assert "5,00 € bezahlt, weitere 2,50 € offen" in page


def _fee_at_entry(client):
    from skibasar.services import reports

    with client.app.state.session_factory() as s:
        return reports.build(s).fee_at_entry_cents


def test_undo_after_fee_collected_keeps_the_cash_recorded(client):
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "1,00"})
    url = _seller(client)
    for n in range(3):
        _article(client, url, n)
    client.post(f"{url}/gebuehr")
    client.post(f"{url}/artikel/zurueck")
    # 3,00 € are in the till, even though only 2 articles are left
    assert _fee_at_entry(client) == 300
    assert "Angebotsgebühr 3,00 € bezahlt" in client.get(url).text
    # The re-entered article is covered by the earlier payment, nothing more to pay
    _article(client, url, 2)
    assert "für alle 3 Artikel bezahlt" in client.get(url).text
    _article(client, url, 3)
    client.post(f"{url}/gebuehr")
    assert _fee_at_entry(client) == 400


def test_fee_change_between_two_payments_keeps_the_seller_rate(client):
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "1,00"})
    url = _seller(client)
    for n in range(3):
        _article(client, url, n)
    client.post(f"{url}/gebuehr")
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "2,00"})
    _article(client, url, 3)
    _article(client, url, 4)
    page = client.get(url).text
    assert "Gebühr 2,00 € kassiert" in page and "weitere 2,00 € offen" in page
    client.post(f"{url}/gebuehr")
    assert _fee_at_entry(client) == 500
    # A seller who has not paid yet pays the new rate
    other = _seller(client, name="Maier")
    _article(client, other, 5)
    assert "Gebühr 2,00 € kassiert" in client.get(other).text


def test_paid_seller_cannot_silently_become_fee_exempt(client):
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "1,00"})
    url = _seller(client)
    _article(client, url, 0)
    client.post(f"{url}/gebuehr")
    r = client.post(url, data={"name": "Huber", "fee_exempt": "on"})
    assert r.status_code == 422 and "1,00 € Angebotsgebühr kassiert" in r.text
    assert _fee_at_entry(client) == 100
    # Both flags at once are refused in the Übersicht; refund = untick "paid", then exempt
    data = {"name": "Huber", "fee_exempt": "on", "offer_fee_paid_at_entry": "on"}
    assert client.post("/uebersicht/verkaeufer/1", data=data).status_code == 422
    client.post("/uebersicht/verkaeufer/1", data={"name": "Huber", "fee_exempt": "on"})
    assert _fee_at_entry(client) == 0


def test_paid_ticked_before_any_article_does_not_cover_later_ones(client):
    client.post("/einstellungen", data={"name": "B", "offer_fee_private": "1,00"})
    url = _seller(client)
    client.post("/uebersicht/verkaeufer/1", data={"name": "Huber", "offer_fee_paid_at_entry": "on"})
    for n in range(2):
        _article(client, url, n)
    assert _fee_at_entry(client) == 0
    assert "Gebühr 2,00 € kassiert" in client.get(url).text
