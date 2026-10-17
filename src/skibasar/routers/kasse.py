"""Checkout screens. The cart lives in the page (hidden fields), so devices never share state."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Event, Sale
from ..money import MoneyError, format_eur, parse_eur
from ..services import kasse
from ..services.kasse import KasseError
from .setup import _client, get_session, templates

router = APIRouter(prefix="/kasse")


def _numbers(values: list) -> list[int]:
    return [int(v) for v in values if str(v).strip().isdigit()]


def _cart_page(
    request: Request, s: Session, numbers: list[int], *, error=None, added=None, status=200
):
    articles = kasse.load_cart(s, numbers)
    ctx = {
        "articles": articles,
        "total": sum(a.price_cents for a in articles),
        "error": error,
        "added": added,
        "last_sale": s.scalar(select(Sale).order_by(Sale.id.desc()).limit(1)),
    }
    return templates.TemplateResponse(request, "kasse.html", ctx, status_code=status)


@router.get("", response_class=HTMLResponse)
def cart_empty(request: Request, s: Session = Depends(get_session)):
    return _cart_page(request, s, [])


@router.post("/artikel", response_class=HTMLResponse)
async def cart_add(request: Request, s: Session = Depends(get_session)):
    data = await request.form()
    cart = _numbers(data.getlist("cart"))
    raw = str(data.get("number", "")).strip()
    if not raw.isdigit():
        error = "Bitte eine Artikelnummer eingeben" if not raw else f"„{raw}“ ist keine Nummer"
        return _cart_page(request, s, cart, error=error, status=422)
    try:
        article = kasse.lookup(s, int(raw), cart)
    except KasseError as e:
        return _cart_page(request, s, cart, error=str(e), status=422)
    return _cart_page(request, s, [*cart, article.number], added=article.number)


@router.post("/entfernen", response_class=HTMLResponse)
async def cart_remove(request: Request, s: Session = Depends(get_session)):
    data = await request.form()
    cart = _numbers(data.getlist("cart"))
    remove = str(data.get("remove", ""))
    if remove == "last":
        cart = cart[:-1]
    elif remove.isdigit():
        cart = [n for n in cart if n != int(remove)]
    return _cart_page(request, s, cart)


@router.post("/rueckgeld", response_class=HTMLResponse)
async def change_due(request: Request):
    data = await request.form()
    total = int(str(data.get("total", "0")) or 0)
    given = str(data.get("given", "")).strip()
    if not given:
        return HTMLResponse("")
    try:
        diff = parse_eur(given) - total
    except MoneyError:
        return HTMLResponse('<p class="error">Betrag nicht lesbar</p>')
    if diff < 0:
        return HTMLResponse(f'<p class="error">Es fehlen {format_eur(-diff)}</p>')
    return HTMLResponse(f'<p class="change ok">Rückgeld: <strong>{format_eur(diff)}</strong></p>')


@router.post("/abschluss", response_class=HTMLResponse)
async def complete(request: Request, s: Session = Depends(get_session)):
    data = await request.form()
    cart = _numbers(data.getlist("cart"))
    try:
        sale = kasse.complete_sale(s, cart, client=_client(request))
    except KasseError as e:
        s.rollback()
        return _cart_page(request, s, cart, error=str(e), status=409)
    given = str(data.get("given", "")).strip()
    suffix = ""
    if given:
        try:
            suffix = f"?given={parse_eur(given)}"
        except MoneyError:
            pass
    return RedirectResponse(f"/kasse/verkauf/{sale.id}{suffix}", status_code=303)


def _get_sale(s: Session, sale_id: int) -> Sale:
    sale = s.get(Sale, sale_id)
    if sale is None:
        raise HTTPException(404, "Verkauf nicht gefunden")
    return sale


@router.get("/verkauf/{sale_id}", response_class=HTMLResponse)
def sale_done(request: Request, sale_id: int, given: int = 0, s: Session = Depends(get_session)):
    sale = _get_sale(s, sale_id)
    ctx = {"sale": sale, "given": given, "error": None}
    return templates.TemplateResponse(request, "kasse_verkauf.html", ctx)


@router.post("/verkauf/{sale_id}/storno", response_class=HTMLResponse)
def sale_cancel(request: Request, sale_id: int, s: Session = Depends(get_session)):
    sale = _get_sale(s, sale_id)
    try:
        kasse.cancel_sale(s, sale, client=_client(request))
    except KasseError as e:
        s.rollback()
        ctx = {"sale": sale, "given": 0, "error": str(e)}
        return templates.TemplateResponse(request, "kasse_verkauf.html", ctx, status_code=409)
    return RedirectResponse(f"/kasse/verkauf/{sale_id}?storniert=1", status_code=303)


@router.get("/verkauf/{sale_id}/beleg", response_class=HTMLResponse)
def receipt(request: Request, sale_id: int, s: Session = Depends(get_session)):
    ctx = {"sale": _get_sale(s, sale_id), "event": s.get(Event, 1)}
    return templates.TemplateResponse(request, "print_receipt.html", ctx)


@router.get("/verkaeufe", response_class=HTMLResponse)
def sales_list(request: Request, s: Session = Depends(get_session)):
    sales = list(s.scalars(select(Sale).order_by(Sale.id.desc()).limit(200)))
    return templates.TemplateResponse(request, "kasse_verkaeufe.html", {"sales": sales})
