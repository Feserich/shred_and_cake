import csv
import sqlite3

import pytest
from fastapi.testclient import TestClient

from skibasar.main import create_app


@pytest.fixture
def client(tmp_path):
    c = TestClient(create_app(tmp_path / "data" / "app.db"))
    r = c.post("/annahme/verkaeufer", data={"name": "Huber"}, follow_redirects=False)
    url = r.headers["location"]
    c.post(f"{url}/artikel", data={"expected_number": "0", "description": "Ski", "price": "60,5"})
    c.post("/kasse/abschluss", data={"cart": ["0"]}, follow_redirects=False)
    return c


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f, delimiter=";"))


def test_journal_records_every_write(client, tmp_path):
    rows = _rows(tmp_path / "data" / "journal.csv")
    assert rows[0][0] == "Zeit"
    actions = [(r[3], r[5]) for r in rows[1:]]
    assert ("seller", "create") in actions
    assert ("article", "create") in actions or any(e == "article" for e, _ in actions)
    assert any(e == "sale" for e, _ in actions)


def test_snapshot_csv_has_cents_and_formatted(client, tmp_path):
    client.app.state.backup.snapshot()
    rows = _rows(tmp_path / "data" / "snapshots" / "articles.csv")
    assert rows[1][6:8] == ["6050", "60,50"]
    assert rows[1][9] == "sold"
    assert _rows(tmp_path / "data" / "snapshots" / "sales.csv")[1][2:4] == ["6050", "60,50"]


def test_sqlite_backup_is_consistent_and_rotates(client):
    b = client.app.state.backup
    path = b.sqlite_backup()
    con = sqlite3.connect(path)
    assert con.execute("select count(*) from article").fetchone() == (1,)
    con.close()
    for _ in range(25):
        b.sqlite_backup()
    assert len(b.list_backups()) == 20


def test_rollback_does_not_reach_journal(client, tmp_path):
    before = client.app.state.backup.journal_lines()
    client.post("/kasse/abschluss", data={"cart": ["0"]}, follow_redirects=False)  # already sold
    assert client.app.state.backup.journal_lines() == before


def test_pages_and_export(client, tmp_path):
    assert "Sicherung" in client.get("/sicherung").text
    assert "Sicherung erstellt" in client.post("/sicherung/jetzt").text
    nl = client.get("/notfallliste")
    assert nl.status_code == 200 and "Ski" in nl.text and "60,50" in nl.text
    z = client.get("/sicherung/export.zip")
    assert z.headers["content-type"] == "application/zip"
    out = tmp_path / "usb"
    out.mkdir()
    r = client.post("/sicherung/export", data={"folder": str(out)})
    assert "Exportiert" in r.text
    assert (next(out.iterdir()) / "journal.csv").exists()
    bad = client.post("/sicherung/export", data={"folder": str(tmp_path / "nope")})
    assert bad.status_code == 422 and "existiert nicht" in bad.text
