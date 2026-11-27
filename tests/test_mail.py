import smtplib
import socket

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from skibasar.main import create_app
from skibasar.models import AuditLog, MailSettings, MailStatus, OutgoingMail

MAIL_SETTINGS = {
    "enabled": "1",
    "host": "smtp.example.de",
    "port": "587",
    "security": "starttls",
    "username": "basar@example.de",
    "password": "geheim",
    "sender_email": "basar@example.de",
    "sender_name": "Skiclub Skibasar",
}


class FakeSMTP:
    """Records sent messages; ``fail`` makes send_message raise for given recipients."""

    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail or {}

    def send_message(self, msg):
        exc = self.fail.get(msg["To"])
        if exc is not None:
            raise exc
        self.sent.append(msg)

    def quit(self):
        pass

    def close(self):
        pass


class Server:
    """Stands in for the internet: ``online`` toggles whether connecting works."""

    def __init__(self):
        self.online = True
        self.smtp = FakeSMTP()
        self.logins = []

    def connect(self, settings):
        if not self.online:
            raise socket.gaierror(-3, "Temporary failure in name resolution")
        self.logins.append((settings.host, settings.username, settings.password))
        return self.smtp


@pytest.fixture
def server():
    return Server()


@pytest.fixture
def client(tmp_path, server):
    c = TestClient(create_app(tmp_path / "app.db"))
    c.app.state.mailer.connect = server.connect
    c.post("/einstellungen", data={"name": "Testbasar", "offer_fee_private": "2,00"})
    r = c.post(
        "/annahme/verkaeufer",
        data={"name": "Huber", "first_name": "Anna", "email": "anna@example.org"},
        follow_redirects=False,
    )
    url = r.headers["location"]
    for i, (desc, price) in enumerate([("Ski", "60"), ("Helm", "15,50")]):
        c.post(
            f"{url}/artikel",
            data={
                "expected_number": str(i),
                "description": desc,
                "brand": "Atomic",
                "price": price,
            },
        )
    return c


def _enable(client, **overrides):
    return client.post(
        "/einstellungen/email", data={**MAIL_SETTINGS, **overrides}, follow_redirects=False
    )


def _mails(client):
    with client.app.state.session_factory() as s:
        return list(s.scalars(select(OutgoingMail).order_by(OutgoingMail.id)))


def test_nothing_happens_until_mail_is_set_up(client):
    assert "per E-Mail" not in client.get("/annahme/1").text
    assert client.post("/annahme/1/verlassen").status_code == 204
    client.get("/annahme")
    assert _mails(client) == []


def test_settings_saved_without_leaking_password(client):
    assert _enable(client).status_code == 303
    page = client.get("/einstellungen").text
    assert "smtp.example.de" in page and "geheim" not in page and "gespeichert – leer" in page
    # Empty password keeps the stored one
    _enable(client, password="", sender_name="Neu")
    with client.app.state.session_factory() as s:
        m = s.get(MailSettings, 1)
        assert m.password == "geheim" and m.sender_name == "Neu"
        logs = [
            e.after for e in s.scalars(select(AuditLog).where(AuditLog.entity == "mail_settings"))
        ]
    assert logs and all("geheim" not in a for a in logs)


def test_settings_validation(client):
    r = _enable(client, host="")
    assert r.status_code == 422 and "Server und Absender" in r.text
    r = _enable(client, port="abc")
    assert r.status_code == 422 and "Port" in r.text
    r = _enable(client, sender_email="kein-at")
    assert r.status_code == 422 and "Absender-Adresse" in r.text
    # Switched off, an incomplete account may be saved
    data = {**MAIL_SETTINGS, "host": ""}
    del data["enabled"]
    assert client.post("/einstellungen/email", data=data, follow_redirects=False).status_code == 303


def test_annahme_mail_is_queued_and_sent(client, server):
    _enable(client)
    page = client.get("/annahme/1").text
    assert "Artikelliste per E-Mail an anna@example.org senden" in page
    assert 'name="send_mail" value="1" checked' in page and "sendBeacon" in page
    # Adding articles stays on the seller page: no mail yet
    assert _mails(client) == []

    assert client.post("/annahme/1/verlassen").status_code == 204
    assert "wartet" in client.get("/annahme/1").text
    [queued] = _mails(client)
    assert queued.status == MailStatus.pending and queued.recipient == "anna@example.org"

    assert client.app.state.mailer.send_pending() == 1
    [msg] = server.smtp.sent
    assert msg["To"] == "anna@example.org"
    assert msg["From"] == "Skiclub Skibasar <basar@example.de>"
    assert msg["Subject"] == "Testbasar: Bestätigung Ihrer Artikel"
    text = msg.get_body(("plain",)).get_content()
    assert "Guten Tag Anna Huber" in text
    assert "Nr. 0: Ski (Atomic) – 60,00 €" in text and "Summe 75,50 €" in text
    assert "Angebotsgebühr 4,00 € offen" in text
    html = msg.get_body(("html",)).get_content()
    assert "<td>Helm</td>" in html
    assert server.logins == [("smtp.example.de", "basar@example.de", "geheim")]
    assert _mails(client)[0].status == MailStatus.sent
    assert "gesendet" in client.get("/annahme/1").text


def test_leaving_twice_sends_once_but_changes_send_again(client, server):
    _enable(client)
    client.post("/annahme/1/verlassen")
    client.post("/annahme/1/verlassen")
    assert len(_mails(client)) == 1
    client.post(
        "/annahme/1/artikel",
        data={"expected_number": "2", "description": "Stöcke", "price": "5"},
    )
    client.post("/annahme/1/verlassen")
    assert len(_mails(client)) == 2
    assert "Stöcke" in _mails(client)[1].body_text


def test_switching_seller_on_same_device_sends(client):
    """Fallback if the browser beacon is lost: the next page of this device triggers it."""
    _enable(client)
    client.get("/annahme/1")
    assert _mails(client) == []
    client.get("/annahme")  # back to the list
    assert len(_mails(client)) == 1
    # Opening another seller sends the one that was open before
    client.post(
        "/annahme/1/artikel", data={"expected_number": "2", "description": "X", "price": "1"}
    )
    client.get("/annahme/1")
    r = client.post("/annahme/verkaeufer", data={"name": "Maier"}, follow_redirects=True)
    assert r.status_code == 200 and len(_mails(client)) == 2


def test_unchecked_checkbox_sends_nothing(client):
    _enable(client)
    assert client.post("/annahme/1/email-option", data={}).status_code == 204
    assert 'value="1" checked' not in client.get("/annahme/1").text
    client.post("/annahme/1/verlassen")
    assert _mails(client) == []
    client.post("/annahme/1/email-option", data={"send_mail": "1"})
    client.post("/annahme/1/verlassen")
    assert len(_mails(client)) == 1


def test_html_mail_escapes_user_input(client, server):
    _enable(client)
    client.post(
        "/annahme/1/artikel",
        data={"expected_number": "2", "description": "<b>Stöcke</b>", "price": "5"},
    )
    client.post("/annahme/1/verlassen")
    client.app.state.mailer.send_pending()
    html = server.smtp.sent[0].get_body(("html",)).get_content()
    assert "&lt;b&gt;Stöcke&lt;/b&gt;" in html and "<b>Stöcke" not in html


def test_offline_mails_wait_and_go_out_later(client, server):
    _enable(client)
    server.online = False
    client.post("/annahme/1/verlassen")
    assert client.app.state.mailer.send_pending() == 0
    [m] = _mails(client)
    assert m.status == MailStatus.pending and m.attempts == 1
    assert "keine Internetverbindung" in m.last_error
    page = client.get("/einstellungen").text
    assert "1 E-Mail(s) warten" in page and "keine Internetverbindung" in page

    server.online = True
    r = client.post("/einstellungen/email/senden")
    assert "1 E-Mail(s) gesendet." in r.text
    assert len(server.smtp.sent) == 1 and _mails(client)[0].status == MailStatus.sent


def test_queue_survives_restart(tmp_path, server):
    c = TestClient(create_app(tmp_path / "app.db"))
    c.post("/einstellungen/email", data=MAIL_SETTINGS)
    c.post("/annahme/verkaeufer", data={"name": "Huber", "email": "a@example.org"})
    c.post("/annahme/1/artikel", data={"description": "Ski", "price": "10"})
    c.post("/annahme/1/verlassen")

    restarted = TestClient(create_app(tmp_path / "app.db"))
    restarted.app.state.mailer.connect = server.connect
    assert restarted.app.state.mailer.send_pending() == 1


def test_rejected_recipient_fails_but_others_are_sent(client, server):
    _enable(client)
    client.post("/annahme/verkaeufer", data={"name": "Maier", "email": "weg@example.org"})
    client.post(
        "/annahme/2/artikel", data={"expected_number": "2", "description": "X", "price": "1"}
    )
    server.smtp.fail["weg@example.org"] = smtplib.SMTPRecipientsRefused(
        {"weg@example.org": (550, b"no such user")}
    )
    client.post("/annahme/2/verlassen")
    client.post("/annahme/1/verlassen")
    assert client.app.state.mailer.send_pending() == 1
    sent, failed = sorted(_mails(client), key=lambda m: m.recipient)
    assert failed.status == MailStatus.failed and "abgelehnt" in failed.last_error
    assert sent.status == MailStatus.sent
    # A failed mail is not retried automatically, only on request
    assert client.app.state.mailer.send_pending() == 0
    del server.smtp.fail["weg@example.org"]
    client.post("/einstellungen/email/erneut", data={"mail_id": str(failed.id)})
    assert client.app.state.mailer.send_pending() == 1


def test_connection_lost_midway_keeps_rest_queued(client, server):
    _enable(client)
    client.post("/annahme/verkaeufer", data={"name": "Maier", "email": "anna@example.org"})
    client.post(
        "/annahme/2/artikel", data={"expected_number": "2", "description": "X", "price": "1"}
    )
    client.post("/annahme/1/verlassen")
    client.post("/annahme/2/verlassen")
    server.smtp.fail["anna@example.org"] = smtplib.SMTPServerDisconnected("lost")
    assert client.app.state.mailer.send_pending() == 0
    assert [m.status for m in _mails(client)] == [MailStatus.pending, MailStatus.pending]


def test_discard_waiting_mail(client, server):
    _enable(client)
    server.online = False
    client.post("/annahme/1/verlassen")
    [m] = _mails(client)
    client.post("/einstellungen/email/loeschen", data={"mail_id": str(m.id)})
    assert _mails(client) == []


def test_seller_without_or_with_bad_address(client):
    _enable(client)
    client.post("/annahme/verkaeufer", data={"name": "Ohne"})
    client.post(
        "/annahme/2/artikel", data={"expected_number": "2", "description": "X", "price": "1"}
    )
    assert "per E-Mail" not in client.get("/annahme/2").text
    client.post("/annahme/2/verlassen")
    client.post("/annahme/2", data={"name": "Ohne", "email": "kaputt"})
    assert "per E-Mail" not in client.get("/annahme/2").text
    client.post("/annahme/2/verlassen")
    # Only seller 1 (left when seller 2 was opened) got a mail
    assert [m.seller_id for m in _mails(client)] == [1]


def test_abholung_without_tick_sends_nothing(client):
    _enable(client)
    client.post("/abholung/1/abschluss", data={})
    assert _mails(client) == []


def test_abholung_mail_after_settlement(client, server):
    _enable(client)
    client.post("/kasse/abschluss", data={"cart": ["0"]})
    page = client.get("/abholung/1").text
    assert 'name="send_mail" value="1" checked> Abrechnung per E-Mail an anna@example.org' in page

    r = client.post("/abholung/1/abschluss", data={"returned": ["1"], "send_mail": "1"})
    assert "wartet" in r.text  # the invoice page shows the mail status
    assert "Abrechnung per E-Mail" not in client.get("/abholung/1").text  # settled: no checkbox
    client.app.state.mailer.send_pending()
    [msg] = server.smtp.sent
    assert msg["Subject"] == "Testbasar: Ihre Abrechnung"
    text = msg.get_body(("plain",)).get_content()
    # 60,00 sold, no commission (not set in the fixture), 2 x 2,00 fee -> 56,00
    assert "Nr. 1: Helm – 15,50 € – zurückgegeben" in text
    assert "Angebotsgebühr: − 4,00 €" in text and "Auszahlung: 56,00 €" in text


def test_undo_settlement_drops_waiting_settlement_mail(client, server):
    _enable(client)
    client.post("/einstellungen/admin-pin", data={"new_pin": "4711"})
    server.online = False
    client.post("/annahme/1/verlassen")
    client.post("/abholung/1/abschluss", data={"send_mail": "1"})
    client.post("/abholung/1/zuruecknehmen", data={"admin_pin": "4711"})
    assert [m.kind.value for m in _mails(client)] == ["annahme"]


def test_test_mail(client, server):
    _enable(client)
    r = client.post("/einstellungen/email/test", data={"recipient": "ich@example.org"})
    assert "Test-E-Mail an ich@example.org gesendet" in r.text
    assert server.smtp.sent[0]["Subject"] == "Testbasar: Test-E-Mail"
    server.online = False
    r = client.post("/einstellungen/email/test", data={"recipient": "ich@example.org"})
    assert r.status_code == 422 and "keine Internetverbindung" in r.text
    # Test mails are not queued
    assert _mails(client) == []


def test_wrong_password_keeps_mails_waiting(client, server):
    _enable(client)

    def refuse(settings):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    client.app.state.mailer.connect = refuse
    client.post("/annahme/1/verlassen")
    client.app.state.mailer.send_pending()
    [m] = _mails(client)
    assert m.status == MailStatus.pending and "Passwort" in m.last_error


def test_delete_all_data_clears_queue_keeps_account(client):
    _enable(client)
    client.post("/annahme/1/verlassen")
    client.post("/einstellungen/alle-daten-loeschen", data={"confirm": "LÖSCHEN"})
    with client.app.state.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(OutgoingMail)) == 0
        assert s.get(MailSettings, 1).host == "smtp.example.de"
