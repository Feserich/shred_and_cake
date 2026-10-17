"""Event PIN for LAN clients (login) and the phone connection page with QR code."""

import hashlib
import hmac
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..network import is_local, qr_svg
from .setup import templates

router = APIRouter()

COOKIE = "skibasar_access"
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60


def _token(request: Request) -> str:
    key = request.app.state.access_secret
    return hmac.new(key, request.app.state.event_pin.encode(), hashlib.sha256).hexdigest()


def _client(request: Request) -> str | None:
    return request.client.host if request.client else None


async def pin_gate(request: Request, call_next):
    """Require the event PIN for every non-local client when one is configured."""
    path = request.url.path
    if (
        not request.app.state.event_pin
        or is_local(_client(request))
        or path == "/login"
        or path.startswith("/static/")
    ):
        return await call_next(request)
    cookie = request.cookies.get(COOKIE, "")
    if hmac.compare_digest(cookie, _token(request)):
        return await call_next(request)
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


PHONE_PREFIXES = ("/annahme", "/kasse", "/login", "/static")


def phone_allowed(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PHONE_PREFIXES)


async def laptop_only(request: Request, call_next):
    """Phones (non-local clients) may only use Annahme and Kasse."""
    path = request.url.path
    if not request.app.state.event_pin or is_local(_client(request)) or phone_allowed(path):
        return await call_next(request)
    if path == "/":
        return RedirectResponse("/annahme", status_code=303)
    if request.headers.get("HX-Request"):
        return Response(status_code=403)
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "message": "Diese Seite ist nur am Laptop verfügbar.",
            "hint": "Am Telefon gibt es nur Annahme und Kasse.",
        },
        status_code=403,
    )


def _login_page(request: Request, error: str | None = None, status: int = 200):
    return templates.TemplateResponse(request, "login.html", {"error": error}, status_code=status)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _login_page(request)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, pin: str = Form("")):
    expected = request.app.state.event_pin
    if not expected:
        return RedirectResponse("/", status_code=303)
    failures = request.app.state.login_failures
    client = _client(request) or ""
    count, since = failures.get(client, (0, 0.0))
    now = time.monotonic()
    if count >= MAX_FAILURES and now - since < LOCKOUT_SECONDS:
        return _login_page(request, "Zu viele Versuche. Bitte eine Minute warten.", 429)
    if not hmac.compare_digest(pin.strip().encode(), expected.encode()):
        failures[client] = (count + 1 if now - since < LOCKOUT_SECONDS else 1, now)
        return _login_page(request, "Die PIN stimmt nicht.", 403)
    failures.pop(client, None)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, _token(request), httponly=True, samesite="lax")
    return response


@router.get("/telefon", response_class=HTMLResponse)
def phones(request: Request):
    url = request.app.state.lan_url
    local = is_local(_client(request))
    ctx = {
        "url": url,
        "qr": qr_svg(url) if url else None,
        "pin": request.app.state.event_pin if local else None,
        "has_pin": bool(request.app.state.event_pin),
    }
    return templates.TemplateResponse(request, "telefon.html", ctx)
