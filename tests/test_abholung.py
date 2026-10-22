import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from skibasar.main import create_app
from skibasar.models import Article, ArticleStatus, AuditLog, Event, Seller, SellerType
from skibasar.services import abholung, kasse


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
                type=SellerType.shop, name="Muster", number_range_start=1000, number_range_end=1999
            )
        )
        s.commit()
    assert "Huber" in client.get("/abholung?q=hub").text
    assert "Huber" in client.get("/abholung?q=2").text
    assert "Muster" not in client.get("/abholung?q=2").text
    assert "Muster" in client.get("/abholung?q=1500").text
    assert "Keine Verkäufer" in client.get("/abholung?q=zzz").text


def test_preview_is_read_only_and_calculates(client):
    _sell(client, 0, 1)
    page = client.get("/abholung/1").text
    assert "noch nichts gespeichert" in page
    # 15,55 sold; commission 1,555 -> 1,56 (half up); fee 3 x 2,00 = 6,00; payout 7,99
    assert "15,55 €" in page and "1,56 €" in page and "6,00 €" in page and "7,99 €" in page
    with client.app.state.session_factory() as s:
        assert s.get(Seller, 1).settled_at is None
    assert client.get("/abholung/1/rechnung", follow_redirects=False).status_code == 303


def test_finish_marks_returned_and_blocks_sales(client):
    _sell(client, 0)
    r = client.post(
        "/abholung/1/abschluss",
        data={"returned": ["1", "2"], "expected_payout": "300"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/abholung/1/rechnung")
    invoice = client.get("/abholung/1/rechnung").text
    assert "Unterschrift" in invoice and "zurückgegeben" in invoice and "3,00 €" in invoice
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
    assert "Verkäufer zahlt" in page and "6,00 €" in page


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
    assert "3,00 €" in before


def test_unsold_articles_are_ticked_as_returned_by_default(client):
    _sell(client, 0)
    page = client.get("/abholung/1").text
    for number in (1, 2):
        assert f'name="returned" value="{number}" checked' in page
    assert 'name="returned" value="0"' not in page  # sold articles cannot be returned


def test_finish_does_not_return_article_sold_in_the_meantime(client, monkeypatch):
    stale = None
    factory = client.app.state.session_factory
    with factory() as s:
        stale = abholung.preview(s, s.get(Seller, 1))
    assert [a.number for a in stale.unsold] == [0, 1, 2]
    _sell(client, 0)  # another device sells article 0 after the preview was built
    monkeypatch.setattr(abholung, "preview", lambda s, seller: stale)
    with factory() as s, pytest.raises(abholung.AbholungError, match="verkauft"):
        abholung.finish(s, s.get(Seller, 1), returned_numbers=[0, 1, 2])
    with factory() as s:
        assert s.get(Seller, 1).settled_at is None
        statuses = {a.number: a.status for a in s.scalars(select(Article))}
    assert statuses == {
        0: ArticleStatus.sold,
        1: ArticleStatus.available,
        2: ArticleStatus.available,
    }


def test_finish_after_sale_in_other_session_refuses_stale_payout(client):
    factory = client.app.state.session_factory
    with factory() as a, factory() as b:
        seller = a.get(Seller, 1)
        shown = abholung.preview(a, seller).settlement.payout_cents
        kasse.complete_sale(b, [0])
        with pytest.raises(abholung.AbholungError, match="geändert"):
            abholung.finish(a, seller, returned_numbers=[1, 2], expected_payout_cents=shown)
    with factory() as s:
        assert s.get(Seller, 1).settled_at is None


def test_undo_settlement(client, monkeypatch):
    monkeypatch.delenv("SKIBASAR_ADMIN_PIN", raising=False)
    _sell(client, 0)
    client.post("/abholung/1/abschluss", data={"returned": ["1", "2"], "expected_payout": "300"})
    page = client.get("/abholung/1").text
    assert "Abrechnung zurücknehmen" in page and "data-confirm" in page
    r = client.post("/abholung/1/zuruecknehmen", data={"admin_pin": "4711"})
    assert r.status_code == 422 and "noch keine eingerichtet" in r.text
    client.post("/einstellungen/admin-pin", data={"new_pin": "4711"})
    r = client.post("/abholung/1/zuruecknehmen", data={"admin_pin": "0000"})
    assert r.status_code == 422 and "PIN ist falsch" in r.text
    with client.app.state.session_factory() as s:
        assert s.get(Seller, 1).settled_at is not None
    r = client.post("/abholung/1/zuruecknehmen", data={"admin_pin": "4711"}, follow_redirects=True)
    assert "Abrechnung zurückgenommen" in r.text and "Vorschau" in r.text
    with client.app.state.session_factory() as s:
        seller = s.get(Seller, 1)
        assert seller.settled_at is None and seller.settled_payout_cents is None
        assert seller.settled_sold_total_cents is None
        assert seller.settled_commission_cents is None and seller.settled_open_fee_cents is None
        status = {a.number: a.status for a in seller.articles}
        assert status[0] == ArticleStatus.sold
        assert status[1] == status[2] == ArticleStatus.available
        actions = [a.action for a in s.query(AuditLog).filter_by(entity="seller")]
        assert "unsettle" in actions
    # not settled any more: a second undo is refused, and the seller can be settled again
    r = client.post("/abholung/1/zuruecknehmen", data={"admin_pin": "4711"})
    assert r.status_code == 422 and "nicht abgerechnet" in r.text
    client.post("/abholung/1/abschluss", data={"returned": ["1", "2"], "expected_payout": "300"})
    assert client.get("/abholung/1/rechnung").status_code == 200
