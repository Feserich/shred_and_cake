from fastapi.testclient import TestClient

from skibasar.main import create_app
from skibasar.network import qr_svg


def _client(tmp_path, pin=None, lan=None, host="testclient"):
    app = create_app(tmp_path / "t.db", event_pin=pin, lan_address=lan)
    return TestClient(app, client=(host, 50000))


def test_no_pin_means_open(tmp_path):
    assert _client(tmp_path).get("/annahme").status_code == 200


def test_remote_client_is_redirected_to_login(tmp_path):
    c = _client(tmp_path, pin="123456")
    r = c.get("/annahme", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/static/app.css").status_code == 200


def test_htmx_request_gets_401(tmp_path):
    r = _client(tmp_path, pin="123456").get("/kasse", headers={"HX-Request": "true"})
    assert r.status_code == 401 and r.headers["HX-Redirect"] == "/login"


def test_localhost_is_exempt(tmp_path):
    assert _client(tmp_path, pin="123456", host="127.0.0.1").get("/annahme").status_code == 200


def test_login_flow(tmp_path):
    c = _client(tmp_path, pin="123456")
    bad = c.post("/login", data={"pin": "000000"})
    assert bad.status_code == 403 and "PIN stimmt nicht" in bad.text
    ok = c.post("/login", data={"pin": "123456"}, follow_redirects=False)
    assert ok.status_code == 303
    assert c.get("/annahme").status_code == 200


def test_login_lockout(tmp_path):
    c = _client(tmp_path, pin="123456")
    for _ in range(5):
        c.post("/login", data={"pin": "0"})
    r = c.post("/login", data={"pin": "123456"})
    assert r.status_code == 429 and "Zu viele Versuche" in r.text


def test_phone_page_shows_qr_and_pin_only_locally(tmp_path):
    url = "http://192.168.1.20:8000"
    local = _client(tmp_path, pin="123456", lan=url, host="127.0.0.1").get("/telefon")
    assert "<svg" in local.text and url in local.text and "123456" in local.text
    c = _client(tmp_path, pin="123456", lan=url)
    c.post("/login", data={"pin": "123456"})
    assert "123456" not in c.get("/telefon").text.replace("value=", "")


def test_qr_is_svg():
    assert qr_svg("http://x").startswith("<svg")


def _phone(tmp_path):
    c = _client(tmp_path, pin="123456")
    c.post("/login", data={"pin": "123456"})
    return c


def test_phone_may_use_annahme_and_kasse(tmp_path):
    c = _phone(tmp_path)
    assert c.get("/annahme").status_code == 200
    assert c.get("/kasse").status_code == 200


def test_phone_is_kept_off_laptop_pages(tmp_path):
    c = _phone(tmp_path)
    for path in (
        "/abholung",
        "/uebersicht",
        "/haendler",
        "/einstellungen",
        "/sicherung",
        "/telefon",
    ):
        assert c.get(path).status_code == 403, path
    assert c.get("/uebersicht", headers={"HX-Request": "true"}).status_code == 403


def test_phone_home_goes_to_annahme(tmp_path):
    r = _phone(tmp_path).get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/annahme"


def test_phone_nav_hides_laptop_links(tmp_path):
    html = _phone(tmp_path).get("/annahme").text
    assert (
        'href="/kasse"' in html
        and 'href="/uebersicht"' not in html
        and 'href="/einstellungen"' not in html
    )


def test_localhost_keeps_everything(tmp_path):
    c = _client(tmp_path, pin="123456", host="127.0.0.1")
    assert c.get("/uebersicht").status_code == 200
    assert 'href="/uebersicht"' in c.get("/annahme").text


def test_phone_gets_german_error_page_for_laptop_pages(tmp_path):
    c = _client(tmp_path, pin="123456")
    c.post("/login", data={"pin": "123456"})
    r = c.get("/uebersicht")
    assert r.status_code == 403
    assert "nur am Laptop verfügbar" in r.text and "<html" in r.text


def test_start_page_buttons_depend_on_device(tmp_path):
    laptop = _client(tmp_path, pin="123456", host="127.0.0.1").get("/").text
    assert "/abholung" in laptop and "/uebersicht" in laptop and "Erster Start" in laptop
    phone = _client(tmp_path, pin="123456")
    phone.post("/login", data={"pin": "123456"})
    assert "/abholung" not in phone.get("/annahme").text


def test_telefon_page_has_no_command_line_hint(tmp_path):
    text = _client(tmp_path, host="127.0.0.1").get("/telefon").text
    assert "Skibasar-mit-Telefonen.bat" in text and "--lan" not in text


def test_start_page_asks_for_admin_pin_until_one_is_set(tmp_path):
    c = _client(tmp_path, host="127.0.0.1")
    assert "noch keine Admin-PIN eingerichtet" in c.get("/").text
    c.post("/einstellungen/admin-pin", data={"new_pin": "4711"})
    page = c.get("/").text
    assert "noch keine Admin-PIN eingerichtet" not in page and "(erledigt)" in page


def test_gesamtabrechnung_is_part_of_the_abschluss_page(tmp_path):
    c = _client(tmp_path, host="127.0.0.1")
    r = c.get("/gesamtabrechnung", follow_redirects=False)
    assert r.headers["location"] == "/abschluss#gesamtabrechnung"
    page = c.get("/abschluss").text
    assert '<span class="step-n">5</span>Abschluss' in page
    assert 'href="/gesamtabrechnung"' not in page
    assert page.index("<h2>Ergebnis</h2>") < page.index('<h2 id="gesamtabrechnung">')
