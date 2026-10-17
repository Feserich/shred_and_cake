"""Application factory and entry point."""

import argparse
import secrets
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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

    return app


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
