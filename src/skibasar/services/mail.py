"""Optional confirmation mails to sellers: compose, queue, and send in the background.

Mails are queued in the database (``mail_outbox``) with their content frozen, so a mail queued
without internet goes out later unchanged, also after a restart. A background thread
(``Mailer``) retries waiting mails every minute and right after a new mail was queued.
"""

import hashlib
import json
import re
import smtplib
import socket
import ssl
import threading
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..models import (
    Event,
    MailKind,
    MailSecurity,
    MailSettings,
    MailStatus,
    OutgoingMail,
    Seller,
)
from ..money import format_eur
from . import audit
from .abholung import preview, settled_fee_status
from .annahme import fee_status

TIMEOUT_S = 20
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "templates" / "mail"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["eur"] = format_eur


class MailError(ValueError):
    pass


def valid_address(address: str) -> bool:
    return bool(_EMAIL_RE.match(address.strip()))


def get_settings(s: Session) -> MailSettings:
    return s.get(MailSettings, 1)


def save_settings(
    s: Session,
    *,
    enabled: bool,
    host: str,
    port: str,
    security: str,
    username: str,
    password: str,
    sender_email: str,
    sender_name: str,
    client: str = "",
) -> MailSettings:
    """Validate and store the SMTP account. An empty ``password`` keeps the stored one."""
    host, sender_email = host.strip(), sender_email.strip()
    port = port.strip()
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise MailError("Der Port muss eine Zahl zwischen 1 und 65535 sein")
    try:
        security_value = MailSecurity(security)
    except ValueError as e:
        raise MailError("Unbekannte Verschlüsselung") from e
    if sender_email and not valid_address(sender_email):
        raise MailError("Die Absender-Adresse ist keine gültige E-Mail-Adresse")
    if enabled and not (host and sender_email):
        raise MailError("Zum Einschalten bitte mindestens Server und Absender-Adresse eintragen")
    m = get_settings(s)
    values = {
        "enabled": enabled,
        "host": host,
        "port": int(port),
        "security": security_value,
        "username": username.strip(),
        "sender_email": sender_email,
        "sender_name": sender_name.strip(),
    }
    before = {k: getattr(m, k) for k in values}
    for key, value in values.items():
        setattr(m, key, value)
    password_changed = bool(password)
    if password_changed:
        m.password = password
    # The password itself never goes into the protocol
    audit.log(
        s,
        "mail_settings",
        1,
        "update",
        before,
        {**values, "password_changed": password_changed},
        client,
    )
    s.commit()
    return m


# -- composing -------------------------------------------------------------


def _common(s: Session, seller: Seller) -> dict:
    event = s.get(Event, 1)
    settings = get_settings(s)
    return {
        "seller": seller,
        "event": event,
        "greeting_name": seller.display_name,
        "signature": settings.sender_name or event.name,
    }


def _render(kind: str, ctx: dict) -> tuple[str, str]:
    return (
        _env.get_template(f"{kind}.txt").render(ctx).strip() + "\n",
        _env.get_template(f"{kind}.html").render(ctx),
    )


def compose_annahme(s: Session, seller: Seller) -> tuple[str, str, str]:
    """Subject, text and HTML of the confirmation of all articles taken in."""
    ctx = {
        **_common(s, seller),
        "articles": list(seller.articles),
        "total": sum(a.price_cents for a in seller.articles),
        "fee_status": fee_status(s.get(Event, 1), seller),
    }
    subject = f"{ctx['event'].name}: Bestätigung Ihrer Artikel"
    return (subject, *_render("annahme", ctx))


def compose_abholung(s: Session, seller: Seller) -> tuple[str, str, str]:
    """Subject, text and HTML of the settlement (like the printed invoice)."""
    if seller.settled_at is None:
        raise MailError("Dieser Verkäufer ist noch nicht abgerechnet")
    p = preview(s, seller)
    ctx = {
        **_common(s, seller),
        "p": p,
        "r": p.settlement,
        "fee_status": settled_fee_status(seller, p.settlement),
    }
    subject = f"{ctx['event'].name}: Ihre Abrechnung"
    return (subject, *_render("abholung", ctx))


_COMPOSERS = {MailKind.annahme: compose_annahme, MailKind.abholung: compose_abholung}


def queue_for_seller(s: Session, seller: Seller, kind: MailKind, client: str = "") -> OutgoingMail:
    """Queue a confirmation for the seller's stored address; the Mailer sends it when online."""
    if not get_settings(s).active:
        raise MailError("Der E-Mail-Versand ist nicht eingerichtet (Einstellungen)")
    recipient = seller.email.strip()
    if not recipient:
        raise MailError("Für diesen Verkäufer ist keine E-Mail-Adresse eingetragen")
    if not valid_address(recipient):
        raise MailError(f"„{recipient}“ ist keine gültige E-Mail-Adresse – bitte korrigieren")
    if kind == MailKind.annahme and not seller.articles:
        raise MailError("Es sind noch keine Artikel erfasst")
    subject, text, html = _COMPOSERS[kind](s, seller)
    mail = OutgoingMail(
        seller_id=seller.id,
        kind=kind,
        recipient=recipient,
        subject=subject,
        body_text=text,
        body_html=html,
    )
    s.add(mail)
    s.flush()
    audit.log(s, "mail", mail.id, "queue", None, {"kind": kind.value, "to": recipient}, client)
    s.commit()
    return mail


def can_mail(s: Session, seller: Seller) -> bool:
    """Mail is set up and the seller has a usable address: only then the checkbox is shown."""
    return get_settings(s).active and valid_address(seller.email)


def _annahme_signature(s: Session, seller: Seller) -> str:
    content = [
        seller.email.strip(),
        fee_status(s.get(Event, 1), seller),
        [
            [a.number, a.description, a.brand, a.size, a.color, a.price_cents]
            for a in seller.articles
        ],
    ]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def confirm_annahme(s: Session, seller: Seller, client: str = "") -> OutgoingMail | None:
    """Queue the article list once the volunteer has left the seller's page.

    Called on every way of leaving, so it must be idempotent: nothing is queued when the
    checkbox is off, there is nothing to send, or the list is unchanged since the last mail.
    """
    s.refresh(seller)
    if (
        not seller.annahme_mail
        or seller.settled_at is not None
        or not seller.articles
        or not can_mail(s, seller)
    ):
        return None
    signature = _annahme_signature(s, seller)
    if signature == seller.annahme_mail_sig:
        return None
    seller.annahme_mail_sig = signature
    return queue_for_seller(s, seller, MailKind.annahme, client)


def mails_for_seller(s: Session, seller: Seller) -> list[OutgoingMail]:
    return list(
        s.scalars(
            select(OutgoingMail)
            .where(OutgoingMail.seller_id == seller.id)
            .order_by(OutgoingMail.id.desc())
        )
    )


def outbox(s: Session, limit: int = 50) -> list[OutgoingMail]:
    """Waiting and failed mails first, then the most recently sent ones."""
    open_mails = s.scalars(
        select(OutgoingMail).where(OutgoingMail.status != MailStatus.sent).order_by(OutgoingMail.id)
    ).all()
    sent = s.scalars(
        select(OutgoingMail)
        .where(OutgoingMail.status == MailStatus.sent)
        .order_by(OutgoingMail.id.desc())
        .limit(limit)
    ).all()
    return [*open_mails, *sent]


def retry(s: Session, mail_id: int | None = None) -> int:
    """Put a failed mail (or all failed ones) back into the queue."""
    q = update(OutgoingMail).where(OutgoingMail.status == MailStatus.failed)
    if mail_id is not None:
        q = q.where(OutgoingMail.id == mail_id)
    count = s.execute(q.values(status=MailStatus.pending, last_error="")).rowcount
    s.commit()
    return count


def discard(s: Session, mail_id: int) -> None:
    """Delete a mail that was not sent (yet)."""
    s.execute(
        delete(OutgoingMail).where(
            OutgoingMail.id == mail_id, OutgoingMail.status != MailStatus.sent
        )
    )
    s.commit()


# -- sending ---------------------------------------------------------------


def describe_error(exc: BaseException) -> str:
    """Plain German reason for a failed attempt (shown in the queue)."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Anmeldung abgelehnt – Benutzername oder Passwort prüfen"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Empfängeradresse vom Server abgelehnt"
    if isinstance(exc, smtplib.SMTPResponseException):
        message = exc.smtp_error
        if isinstance(message, bytes):
            message = message.decode(errors="replace")
        return f"Der Server meldet: {exc.smtp_code} {message}"
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return "Der Server unterstützt diese Verschlüsselung nicht – Verschlüsselung/Port prüfen"
    if isinstance(exc, socket.gaierror):
        return "Server nicht gefunden – keine Internetverbindung oder falscher Servername"
    if isinstance(exc, ssl.SSLError):
        return "Verschlüsselte Verbindung fehlgeschlagen – Verschlüsselung/Port prüfen"
    if isinstance(exc, TimeoutError | ConnectionError | smtplib.SMTPServerDisconnected):
        return "Keine Verbindung zum Mailserver – Internetverbindung prüfen"
    return f"Fehler beim Senden: {exc}"


def _permanent(exc: BaseException) -> bool:
    """The server rejected this one mail for good; others may still go through."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return True
    return (
        isinstance(exc, smtplib.SMTPDataError | smtplib.SMTPSenderRefused) and exc.smtp_code >= 500
    )


def connect(settings: MailSettings) -> smtplib.SMTP:
    """Open and log in an SMTP connection as configured."""
    context = ssl.create_default_context()
    if settings.security == MailSecurity.ssl:
        smtp = smtplib.SMTP_SSL(settings.host, settings.port, timeout=TIMEOUT_S, context=context)
    else:
        smtp = smtplib.SMTP(settings.host, settings.port, timeout=TIMEOUT_S)
    try:
        if settings.security == MailSecurity.starttls:
            smtp.starttls(context=context)
        if settings.username:
            smtp.login(settings.username, settings.password)
    except BaseException:
        smtp.close()
        raise
    return smtp


def build_message(settings: MailSettings, recipient: str, subject: str, text: str, html: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.sender_name, settings.sender_email))
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.sender_email.rsplit("@", 1)[-1])
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


class Mailer:
    """Sends waiting mails from the queue; safe to call from any thread."""

    def __init__(self, factory: sessionmaker[Session], interval_s: float = 60):
        self.factory = factory
        self.interval_s = interval_s
        self.connect = connect  # replaced in tests
        self._send_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _snapshot_settings(self, s: Session) -> MailSettings | None:
        settings = get_settings(s)
        if settings is None or not settings.active:
            return None
        s.expunge(settings)  # used outside the session while talking to the server
        return settings

    def send_pending(self) -> int:
        """One pass over the queue; returns the number of mails sent."""
        if not self._send_lock.acquire(blocking=False):
            return 0  # another pass is running
        try:
            return self._send_pending()
        finally:
            self._send_lock.release()

    def _send_pending(self) -> int:
        with self.factory() as s:
            settings = self._snapshot_settings(s)
            if settings is None:
                return 0
            waiting = [
                (m.id, m.recipient, m.subject, m.body_text, m.body_html)
                for m in s.scalars(
                    select(OutgoingMail)
                    .where(OutgoingMail.status == MailStatus.pending)
                    .order_by(OutgoingMail.id)
                )
            ]
        if not waiting:
            return 0
        sent = 0
        try:
            smtp = self.connect(settings)
        except Exception as e:  # noqa: BLE001 - offline etc.: keep everything queued
            self._note_waiting([w[0] for w in waiting], describe_error(e))
            return 0
        try:
            for index, (mail_id, recipient, subject, text, html) in enumerate(waiting):
                try:
                    smtp.send_message(build_message(settings, recipient, subject, text, html))
                except Exception as e:  # noqa: BLE001
                    if _permanent(e):
                        self._finish(mail_id, MailStatus.failed, describe_error(e))
                        continue
                    # Connection lost: this and the rest stay queued for the next pass
                    self._note_waiting([w[0] for w in waiting[index:]], describe_error(e))
                    break
                self._finish(mail_id, MailStatus.sent, "")
                sent += 1
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                smtp.close()
        return sent

    def _finish(self, mail_id: int, status: MailStatus, error: str) -> None:
        with self.factory() as s:
            mail = s.get(OutgoingMail, mail_id)
            if mail is None:
                return
            mail.status = status
            mail.attempts += 1
            mail.last_error = error
            if status == MailStatus.sent:
                mail.sent_at = datetime.now()
            s.commit()

    def _note_waiting(self, ids: list[int], error: str) -> None:
        with self.factory() as s:
            s.execute(
                update(OutgoingMail)
                .where(OutgoingMail.id.in_(ids), OutgoingMail.status == MailStatus.pending)
                .values(attempts=OutgoingMail.attempts + 1, last_error=error)
            )
            s.commit()

    def send_test(self, recipient: str) -> None:
        """Send a test mail right away (not queued); raises MailError with the reason."""
        recipient = recipient.strip()
        if not valid_address(recipient):
            raise MailError("Bitte eine gültige Empfänger-Adresse für die Test-E-Mail eingeben")
        with self.factory() as s:
            settings = get_settings(s)
            if not settings.configured:
                raise MailError("Bitte zuerst Server und Absender-Adresse speichern")
            s.expunge(settings)
            event_name = s.get(Event, 1).name
        msg = build_message(
            settings,
            recipient,
            f"{event_name}: Test-E-Mail",
            "Diese Test-E-Mail zeigt, dass der E-Mail-Versand des Skibasar-Programms "
            "funktioniert.\n",
            "",
        )
        try:
            smtp = self.connect(settings)
            try:
                smtp.send_message(msg)
            finally:
                try:
                    smtp.quit()
                except Exception:  # noqa: BLE001
                    smtp.close()
        except Exception as e:  # noqa: BLE001
            raise MailError(describe_error(e)) from e

    # -- background thread ----------------------------------------------
    def wake(self) -> None:
        """Try to send now instead of waiting for the next regular pass."""
        self._wake.set()

    def start(self) -> None:
        def loop():
            while not self._stop.is_set():
                self._wake.clear()
                try:
                    self.send_pending()
                except Exception:  # noqa: BLE001 - mail problems must never kill the app
                    pass
                self._wake.wait(self.interval_s)

        self._thread = threading.Thread(target=loop, name="skibasar-mail", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
