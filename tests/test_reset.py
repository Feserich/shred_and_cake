from fastapi.testclient import TestClient
from sqlalchemy import func, select

from skibasar.main import create_app
from skibasar.models import Article, AuditLog, Event, Sale, Seller

URL = "/einstellungen/alle-daten-loeschen"


def _client(tmp_path):
    c = TestClient(create_app(tmp_path / "data" / "app.db"))
    c.post(
        "/einstellungen",
        data={"name": "Testbasar", "offer_fee_private": "2,00", "private_number_start": "0"},
    )
    r = c.post("/annahme/verkaeufer", data={"name": "Huber"}, follow_redirects=False)
    url = r.headers["location"]
    c.post(f"{url}/artikel", data={"expected_number": "0", "description": "Ski", "price": "60"})
    c.post("/kasse/abschluss", data={"cart": ["0"]}, follow_redirects=False)
    c.post("/haendler", data={"name": "Shop", "range_start": "1000", "range_end": "1999"})
    return c


def _count(client, model):
    with client.app.state.session_factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_delete_all_data_keeps_settings(tmp_path):
    c = _client(tmp_path)
    assert "Alle Daten löschen" in c.get("/einstellungen").text
    backups_before = len(c.app.state.backup.list_backups())

    r = c.post(URL, data={"confirm": "löschen"}, follow_redirects=True)
    assert r.status_code == 200 and "Alle Daten gelöscht" in r.text
    for model in (Seller, Article, Sale):
        assert _count(c, model) == 0
    with c.app.state.session_factory() as s:
        assert s.get(Event, 1).name == "Testbasar"
        assert s.get(Event, 1).offer_fee_private_cents == 200
        assert [e.action for e in s.scalars(select(AuditLog))] == ["delete_all_data"]

    # Safety backup and archived journal; the new journal holds only the deletion
    b = c.app.state.backup
    assert len(b.list_backups()) == backups_before + 1
    assert list(b.backup_dir.glob("journal-*.csv"))
    assert b.journal_lines() == 1

    # The Basar starts afresh: number 0 is free again
    r = c.post("/annahme/verkaeufer", data={"name": "Echt"}, follow_redirects=False)
    r = c.post(
        f"{r.headers['location']}/artikel",
        data={"expected_number": "0", "description": "Ski", "price": "10"},
    )
    assert _count(c, Article) == 1


def test_delete_all_data_needs_confirmation(tmp_path):
    c = _client(tmp_path)
    r = c.post(URL, data={"confirm": "ja"})
    assert r.status_code == 422 and "LÖSCHEN" in r.text
    assert _count(c, Seller) == 2
    assert not list(c.app.state.backup.backup_dir.glob("journal-*.csv"))


def test_delete_all_data_needs_admin_pin_when_set(tmp_path):
    c = _client(tmp_path)
    c.post("/einstellungen/admin-pin", data={"new_pin": "4711"})
    assert 'name="pin"' in c.get("/einstellungen").text

    r = c.post(URL, data={"confirm": "LÖSCHEN", "pin": "0000"})
    assert r.status_code == 422 and "falsch" in r.text
    assert _count(c, Seller) == 2

    r = c.post(URL, data={"confirm": "LÖSCHEN", "pin": "4711"}, follow_redirects=True)
    assert "Alle Daten gelöscht" in r.text and _count(c, Seller) == 0
    # The PIN itself is kept
    r = c.post(URL, data={"confirm": "LÖSCHEN", "pin": "0000"})
    assert r.status_code == 422
