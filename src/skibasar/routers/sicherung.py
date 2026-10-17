"""Sicherung (backups/export) and the printable Notfallliste."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models import Article, Event
from .setup import get_session, templates

router = APIRouter()


def _backup(request: Request):
    backup = request.app.state.backup
    if backup is None:
        raise HTTPException(404, "Sicherungen sind in dieser Sitzung nicht aktiv.")
    return backup


def _page(request: Request, message: str | None = None, error: str | None = None, status=200):
    b = _backup(request)
    backups = b.list_backups()
    ctx = {
        "data_dir": str(b.dir.resolve()),
        "journal_lines": b.journal_lines(),
        "last_snapshot": b.last_snapshot(),
        "last_backup": backups[0].name if backups else None,
        "backup_count": len(backups),
        "message": message,
        "error": error,
    }
    return templates.TemplateResponse(request, "sicherung.html", ctx, status_code=status)


@router.get("/sicherung", response_class=HTMLResponse)
def page(request: Request):
    return _page(request)


@router.post("/sicherung/jetzt", response_class=HTMLResponse)
def backup_now(request: Request):
    path = _backup(request).run_all()
    return _page(request, message=f"Sicherung erstellt: {path.name}")


@router.post("/sicherung/export", response_class=HTMLResponse)
def export_folder(request: Request, folder: str = Form("")):
    folder = folder.strip()
    if not folder or not Path(folder).is_dir():
        return _page(request, error="Dieser Ordner existiert nicht. Bitte Pfad prüfen.", status=422)
    try:
        target = _backup(request).export_to(folder)
    except OSError:
        return _page(request, error="In diesen Ordner kann nicht geschrieben werden.", status=422)
    return _page(request, message=f"Exportiert nach: {target}")


@router.get("/sicherung/export.zip")
def export_zip(request: Request):
    data = _backup(request).export_zip()
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="skibasar-sicherung.zip"'},
    )


@router.get("/notfallliste", response_class=HTMLResponse)
def emergency_list(request: Request, s: Session = Depends(get_session)):
    articles = list(
        s.scalars(select(Article).options(joinedload(Article.seller)).order_by(Article.number))
    )
    ctx = {
        "articles": articles,
        "event": s.get(Event, 1),
        "total": sum(a.price_cents for a in articles),
    }
    return templates.TemplateResponse(request, "print_notfallliste.html", ctx)
