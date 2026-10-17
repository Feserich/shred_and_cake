from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skibasar.config import check_admin_pin
from skibasar.main import create_app
from skibasar.models import AuditLog, Event

FIXTURE = Path(__file__).parent / "fixtures" / "shop_kraemer.csv"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "app.db"))


def test_settings_roundtrip(client):
    r = client.post(
        "/einstellungen",
        data={
            "name": "Basar 2026",
            "event_date": "2026-11-07",
            "private_number_start": "0",
            "offer_fee_private": "2,50",
            "commission_private": "10",
            "offer_fee_shop": "0",
            "commission_shop": "7,5",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200 and "Gespeichert" in r.text
    assert 'value="2,50"' in r.text and 'value="7,5"' in r.text


def test_settings_invalid(client):
    r = client.post("/einstellungen", data={"name": "x", "offer_fee_private": "1,2,3"})
    assert r.status_code == 422 and "kein gültiger Betrag" in r.text


def test_shop_and_import_flow(client):
    r = client.post(
        "/haendler",
        data={"name": "Krämer", "range_start": "1000", "range_end": "1999"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = r.headers["location"]
    r = client.post("/haendler", data={"name": "B", "range_start": "1500", "range_end": "1600"})
    assert r.status_code == 422 and "überschneidet" in r.text

    r = client.post(f"{detail}/import", files={"file": ("k.csv", FIXTURE.read_bytes())})
    assert r.status_code == 200 and "2.545,00 €" in r.text and "Völkl" in r.text
    token = r.text.split(f"{detail}/import/")[1].split('"')[0]
    assert client.get(detail).text.count('<td class="num">10') == 0  # nothing saved yet

    r = client.post(f"{detail}/import/{token}", follow_redirects=True)
    assert "Import übernommen" in r.text and "41" in r.text
    assert client.post(f"{detail}/import/{token}").status_code == 410


def test_bad_import_cannot_commit(client):
    detail = client.post(
        "/haendler",
        data={"name": "K", "range_start": "1", "range_end": "5"},
        follow_redirects=False,
    ).headers["location"]
    r = client.post(f"{detail}/import", files={"file": ("k.csv", FIXTURE.read_bytes())})
    assert "außerhalb" in r.text and "nicht übernommen" in r.text


def test_commission_over_100_percent_rejected(client):
    for field in ("commission_private", "commission_shop"):
        r = client.post("/einstellungen", data={"name": "x", field: "150"})
        assert r.status_code == 422 and "höchstens 100 %" in r.text
    r = client.post("/einstellungen", data={"name": "x", "commission_shop": "100"})
    assert r.status_code == 200


def test_settled_shop_cannot_be_imported(client):
    from skibasar.models import Seller

    r = client.post(
        "/haendler",
        data={"name": "Sport Krämer", "range_start": "1000", "range_end": "1999"},
        follow_redirects=False,
    )
    detail = r.headers["location"]
    assert '<input type="file"' in client.get(detail).text
    r = client.post(f"{detail}/import", files={"file": ("k.csv", FIXTURE.read_bytes())})
    token = r.text.split(f"{detail}/import/")[1].split('"')[0]
    with client.app.state.session_factory() as s:
        from datetime import datetime

        shop = s.get(Seller, int(detail.rsplit("/", 1)[1]))
        shop.settled_at = datetime.now()
        s.commit()
    page = client.get(detail).text
    assert 'type="file"' not in page and "bereits abgerechnet" in page
    r = client.post(f"{detail}/import", files={"file": ("k.csv", FIXTURE.read_bytes())})
    assert r.status_code == 422 and "bereits abgerechnet" in r.text
    assert client.post(f"{detail}/import/{token}").status_code == 422


def test_admin_pin_set_in_app_and_changed(client, monkeypatch):
    monkeypatch.delenv("SKIBASAR_ADMIN_PIN", raising=False)
    assert "noch keine PIN eingerichtet" in client.get("/einstellungen").text
    r = client.post("/einstellungen/admin-pin", data={"new_pin": "12"})
    assert r.status_code == 422 and "mindestens 4 Ziffern" in r.text
    r = client.post("/einstellungen/admin-pin", data={"new_pin": "4711"}, follow_redirects=True)
    assert "Admin-PIN gespeichert" in r.text
    with client.app.state.session_factory() as s:
        stored = s.get(Event, 1).admin_pin_hash
        assert stored and "4711" not in stored
        assert "4711" not in "".join(a.after + a.before for a in s.query(AuditLog))
        assert s.query(AuditLog).filter_by(action="admin_pin").count() == 1
    # changing needs the current PIN
    r = client.post("/einstellungen/admin-pin", data={"current_pin": "0000", "new_pin": "9999"})
    assert r.status_code == 422 and "PIN ist falsch" in r.text
    r = client.post(
        "/einstellungen/admin-pin",
        data={"current_pin": "4711", "new_pin": "9999"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_env_admin_pin_overrides_and_locks_form(client, monkeypatch):
    client.post("/einstellungen/admin-pin", data={"new_pin": "4711"})
    monkeypatch.setenv("SKIBASAR_ADMIN_PIN", "1234")
    assert "kann hier nicht geändert werden" in client.get("/einstellungen").text
    r = client.post("/einstellungen/admin-pin", data={"new_pin": "5555"})
    assert r.status_code == 422
    with client.app.state.session_factory() as s:
        assert check_admin_pin("1234", s.get(Event, 1).admin_pin_hash)
        assert not check_admin_pin("4711", s.get(Event, 1).admin_pin_hash)
