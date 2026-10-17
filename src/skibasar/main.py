"""Application factory and entry point."""

import argparse
import secrets
import threading
import webbrowser
from html import escape
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, config
from .backup import Backup
from .db import init_db, make_engine
from .network import lan_url, qr_terminal
from .routers import abholung, annahme, kasse, reports, setup, sicherung, uebersicht, zugang


def create_app(
    db_path: Path | str = "data/skibasar.db",
    event_pin: str | None = None,
    lan_address: str | None = None,
) -> FastAPI:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_path)
    app = FastAPI(title="Skibasar", version=__version__)
    app.state.session_factory = init_db(engine)

    app.state.pending_imports = {}
    app.state.event_pin = event_pin or config.event_pin()
    app.state.lan_url = lan_address
    app.state.access_secret = secrets.token_bytes(32)
    app.state.login_failures = {}
    app.middleware("http")(zugang.laptop_only)
    app.middleware("http")(zugang.pin_gate)
    app.state.backup = None
    if str(db_path) != ":memory:":
        app.state.backup = Backup(db_path, app.state.session_factory)
        app.state.backup.install()
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(setup.router)
    app.include_router(annahme.router)
    app.include_router(kasse.router)
    app.include_router(abholung.router)
    app.include_router(uebersicht.router)
    app.include_router(reports.router)
    app.include_router(sicherung.router)
    app.include_router(zugang.router)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return setup.templates.TemplateResponse(request, "index.html")

    _install_error_pages(app)
    return app


# Framework defaults ("Not Found", ...) are English; volunteers get plain German instead
_STATUS_MESSAGES = {
    404: "Diese Seite gibt es nicht (mehr).",
    405: "Diese Aktion ist hier nicht möglich.",
}


def _error_page(request: Request, status: int, message: str, hint: str | None = None):
    if request.headers.get("HX-Request"):
        return HTMLResponse(f'<p class="error">{escape(message)}</p>', status_code=status)
    ctx = {"message": message, "hint": hint}
    return setup.templates.TemplateResponse(request, "error.html", ctx, status_code=status)


def _install_error_pages(app: FastAPI) -> None:
    """Show German HTML pages instead of FastAPI's JSON errors and the bare 500 page."""

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail
        if not isinstance(message, str) or message == HTTPStatus(exc.status_code).phrase:
            message = _STATUS_MESSAGES.get(exc.status_code, "Es ist ein Fehler aufgetreten.")
        return _error_page(request, exc.status_code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error_page(
            request,
            422,
            "Die Eingabe konnte nicht verarbeitet werden.",
            "Bitte zurückgehen, die Felder prüfen und es noch einmal versuchen.",
        )

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        # Starlette still re-raises afterwards, so the traceback lands in the console window
        return _error_page(
            request,
            500,
            "Es ist ein unerwarteter Fehler aufgetreten.",
            "Bitte die Seite neu laden. Hilft das nicht, das Programm schließen und neu "
            "starten – bereits gespeicherte Daten bleiben erhalten.",
        )


def run(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="skibasar", description="Skibasar server")
    parser.add_argument("--lan", action="store_true", help="allow phones on the local network")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    address = lan_url(args.port) if args.lan else None
    pin = config.event_pin() or (config.new_event_pin() if args.lan else None)
    db_path = config.data_dir() / "skibasar.db"
    app = create_app(db_path=db_path, event_pin=pin, lan_address=address)
    app.state.backup.start()

    local = f"http://localhost:{args.port}"
    print(f"Skibasar läuft: {local}")
    print(f"Daten: {db_path.parent.resolve()}")
    if args.lan:
        if address:
            print(f"Telefone im WLAN: {address}   PIN: {pin}")
            print(qr_terminal(address))
        else:
            print("Kein WLAN/Netzwerk gefunden: Telefone können sich nicht verbinden.")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(local,)).start()
    uvicorn.run(app, host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port)


if __name__ == "__main__":
    run()
