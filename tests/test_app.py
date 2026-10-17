from fastapi.testclient import TestClient

from skibasar.main import create_app


def test_index(tmp_path):
    client = TestClient(create_app(tmp_path / "app.db"))
    r = client.get("/")
    assert r.status_code == 200
    assert "Skibasar" in r.text


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
