"""Gesamtabrechnung (final report) and its print view."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..models import Event
from ..services import reports
from .setup import get_session, templates

router = APIRouter(prefix="/gesamtabrechnung")


@router.get("", response_class=HTMLResponse)
def report(request: Request, s: Session = Depends(get_session)):
    ctx = {"r": reports.build(s), "event": s.get(Event, 1), "tab": "gesamt"}
    return templates.TemplateResponse(request, "gesamtabrechnung.html", ctx)
