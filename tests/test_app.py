import os

import pytest
from fastapi.testclient import TestClient

from skibasar import __version__, main
from skibasar.main import create_app
from skibasar.routers import setup


def test_index(tmp_path):
    client = TestClient(create_app(tmp_path / "app.db"))
    r = client.get("/")
    assert r.status_code == 200
    assert "Skibasar" in r.text


def test_version_is_shown(tmp_path, capsys):
    client = TestClient(create_app(tmp_path / "app.db"))
    assert f"Skibasar {__version__}" in client.get("/").text
    assert f"Skibasar {__version__}" in client.get("/einstellungen").text
    assert f"Skibasar {__version__}" not in client.get("/annahme").text
    with pytest.raises(SystemExit):
        main.run(["--version"])
    assert capsys.readouterr().out.strip() == f"skibasar {__version__}"


def test_errors_are_german_html_pages_not_json(tmp_path):
    client = TestClient(create_app(tmp_path / "app.db"))
    r = client.get("/abholung/999")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/html")
    assert "Verkäufer nicht gefunden" in r.text and "Zur Startseite" in r.text
    r = client.get("/gibt-es-nicht")
    assert r.status_code == 404 and "Diese Seite gibt es nicht" in r.text
    r = client.get("/abholung/abc")  # path parameter is not a number
    assert r.status_code == 422 and "Eingabe konnte nicht verarbeitet" in r.text
    assert "detail" not in r.text
    r = client.post("/einstellungen", data={})  # required field missing
    assert r.status_code == 422 and "text/html" in r.headers["content-type"]


def test_unexpected_error_shows_german_page(tmp_path):
    app = create_app(tmp_path / "app.db")

    @app.get("/kaputt")
    def broken():
        raise RuntimeError("boom")

    r = TestClient(app, raise_server_exceptions=False).get("/kaputt")
    assert r.status_code == 500 and "unerwarteter Fehler" in r.text and "boom" not in r.text


def test_htmx_errors_are_fragments(tmp_path):
    client = TestClient(create_app(tmp_path / "app.db"))
    r = client.get("/abholung/999", headers={"HX-Request": "true"})
    assert r.status_code == 404 and r.text == '<p class="error">Verkäufer nicht gefunden</p>'


def test_static_urls_change_with_file_content(tmp_path, monkeypatch):
    """Browsers must not keep a cached old app.css/app.js after an update."""
    client = TestClient(create_app(tmp_path / "app.db"))
    page = client.get("/einstellungen").text
    href = page.split('href="/static/app.css?v=')[1].split('"')[0]
    assert client.get(f"/static/app.css?v={href}").status_code == 200

    css = tmp_path / "x.css"
    css.write_text("a{}")
    monkeypatch.setattr(setup, "STATIC_DIR", tmp_path)
    first = setup.static_url("x.css")
    css.write_text("b{}")
    os.utime(css, ns=(1, 1))  # a different mtime, as after an update
    assert setup.static_url("x.css") != first
