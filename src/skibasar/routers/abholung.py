"""Pickup screens: search, read-only settlement preview, explicit commit, A4 invoice."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..models import Event, Seller
from ..services import abholung
from ..services.abholung import AbholungError
from ..services.annahme import fee_status
from .setup import _client, get_session, templates

router = APIRouter(prefix="/abholung")


def _get_seller(s: Session, seller_id: int) -> Seller:
    seller = s.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(404, "Verkäufer nicht gefunden")
    return seller


def _detail(request: Request, s: Session, seller: Seller, *, error=None, status=200):
    event = s.get(Event, 1)
    p = abholung.preview(s, seller)
    status_text = (
        abholung.settled_fee_status(seller, p.settlement)
        if seller.settled_at
        else fee_status(event, seller)
    )
    ctx = {"p": p, "fee_status": status_text, "error": error}
    return templates.TemplateResponse(request, "abholung_detail.html", ctx, status_code=status)


@router.get("", response_class=HTMLResponse)
def search(request: Request, q: str = "", s: Session = Depends(get_session)):
    ctx = {"sellers": abholung.search_sellers(s, q), "q": q}
    return templates.TemplateResponse(request, "abholung.html", ctx)


@router.get("/{seller_id}", response_class=HTMLResponse)
def detail(request: Request, seller_id: int, s: Session = Depends(get_session)):
    return _detail(request, s, _get_seller(s, seller_id))


@router.post("/{seller_id}/abschluss", response_class=HTMLResponse)
async def finish(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _get_seller(s, seller_id)
    data = await request.form()
    returned = [int(v) for v in data.getlist("returned") if str(v).isdigit()]
    expected = str(data.get("expected_payout", "")).lstrip("-")
    try:
        abholung.finish(
            s,
            seller,
            returned_numbers=returned,
            expected_payout_cents=int(data["expected_payout"]) if expected.isdigit() else None,
            client=_client(request),
        )
    except AbholungError as e:
        s.rollback()
        return _detail(request, s, seller, error=str(e), status=409)
    return RedirectResponse(f"/abholung/{seller_id}/rechnung?neu=1", status_code=303)


@router.get("/{seller_id}/rechnung", response_class=HTMLResponse)
def invoice(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _get_seller(s, seller_id)
    if seller.settled_at is None:
        return RedirectResponse(f"/abholung/{seller_id}", status_code=303)
    p = abholung.preview(s, seller)
    ctx = {
        "p": p,
        "event": s.get(Event, 1),
        "fee_status": abholung.settled_fee_status(seller, p.settlement),
    }
    return templates.TemplateResponse(request, "print_invoice.html", ctx)
