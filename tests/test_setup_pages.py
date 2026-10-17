from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skibasar.main import create_app

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
    r = client.post("/einstellungen", data={"name": "x", "offer_fee_private": "1.5"})
    assert r.status_code == 422 and "Ungültiger Betrag" in r.text


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
