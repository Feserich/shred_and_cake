from fastapi.testclient import TestClient

from skibasar.main import create_app


def test_index(tmp_path):
    client = TestClient(create_app(tmp_path / "app.db"))
    r = client.get("/")
    assert r.status_code == 200
    assert "Skibasar" in r.text
