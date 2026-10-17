"""Entry screens: register private sellers, enter their articles, print the seller list."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..models import Event, Seller, SellerType
from ..money import MoneyError, parse_eur
from ..services import annahme
from ..services.annahme import AnnahmeError
from ..services.numbering import next_private_number
from .setup import _client, get_session, templates

router = APIRouter(prefix="/annahme")

_TEXT_FIELDS = ("name", "first_name", "phone", "email", "address", "notes")
_ARTICLE_FIELDS = ("description", "brand", "size", "color", "price")


def _seller_form(seller: Seller | None = None) -> dict:
    if seller is None:
        return {**dict.fromkeys(_TEXT_FIELDS, ""), "fee_exempt": False, "paid": False}
    return {
        **{k: getattr(seller, k) for k in _TEXT_FIELDS},
        "fee_exempt": seller.fee_exempt,
        "paid": seller.offer_fee_paid_at_entry,
    }


async def _seller_values(request: Request) -> dict:
    data = await request.form()
    return {
        **{k: str(data.get(k, "")) for k in _TEXT_FIELDS},
        "fee_exempt": "fee_exempt" in data,
        "paid": "offer_fee_paid_at_entry" in data,
    }


def _save_seller(request: Request, s: Session, seller: Seller | None, form: dict, render):
    try:
        saved = annahme.save_private_seller(
            s,
            seller,
            **{k: form[k] for k in _TEXT_FIELDS},
            fee_exempt=form["fee_exempt"],
            offer_fee_paid_at_entry=form["paid"],
            client=_client(request),
        )
    except AnnahmeError as e:
        s.rollback()
        return render(form, str(e), 422)
    return RedirectResponse(f"/annahme/{saved.id}", status_code=303)


def _get_seller(s: Session, seller_id: int) -> Seller:
    seller = s.get(Seller, seller_id)
    if seller is None or seller.type != SellerType.private:
        raise HTTPException(404, "Verkäufer nicht gefunden")
    return seller


@router.get("", response_class=HTMLResponse)
def entry_home(request: Request, q: str = "", s: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "annahme.html",
        {
            "sellers": annahme.search_private_sellers(s, q),
            "q": q,
            "f": _seller_form(),
            "error": None,
        },
    )


@router.post("/verkaeufer", response_class=HTMLResponse)
async def seller_create(request: Request, s: Session = Depends(get_session)):
    def render(form, error, status):
        ctx = {"sellers": annahme.search_private_sellers(s), "q": "", "f": form, "error": error}
        return templates.TemplateResponse(request, "annahme.html", ctx, status_code=status)

    return _save_seller(request, s, None, await _seller_values(request), render)


def _detail_ctx(s: Session, seller: Seller, **extra) -> dict:
    event = s.get(Event, 1)
    return {
        "seller": seller,
        "next_number": next_private_number(s),
        "total": sum(a.price_cents for a in seller.articles),
        "fee_status": annahme.fee_status(event, seller),
        "a": dict.fromkeys(_ARTICLE_FIELDS, ""),
        "can_undo": annahme.last_undoable_article(s, seller) is not None,
        "suggest": {k: annahme.suggestions(s, k) for k in ("brand", "size", "color")},
        "saved": False,
        "undone": False,
        "error": None,
        "seller_error": None,
        **extra,
    }


@router.get("/{seller_id}", response_class=HTMLResponse)
def seller_detail(
    request: Request,
    seller_id: int,
    saved: int = 0,
    undone: int = 0,
    s: Session = Depends(get_session),
):
    seller = _get_seller(s, seller_id)
    ctx = _detail_ctx(s, seller, f=_seller_form(seller), saved=bool(saved), undone=bool(undone))
    return templates.TemplateResponse(request, "annahme_seller.html", ctx)


@router.post("/{seller_id}", response_class=HTMLResponse)
async def seller_update(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _get_seller(s, seller_id)

    def render(form, error, status):
        ctx = _detail_ctx(s, seller, f=form, seller_error=error)
        return templates.TemplateResponse(request, "annahme_seller.html", ctx, status_code=status)

    return _save_seller(request, s, seller, await _seller_values(request), render)


@router.post("/{seller_id}/artikel", response_class=HTMLResponse)
async def article_create(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _get_seller(s, seller_id)
    data = await request.form()
    form = {k: str(data.get(k, "")) for k in _ARTICLE_FIELDS}
    expected = str(data.get("expected_number", "")).strip()
    try:
        annahme.add_article(
            s,
            seller,
            expected_number=int(expected) if expected.isdigit() else None,
            description=form["description"],
            brand=form["brand"],
            size=form["size"],
            color=form["color"],
            price_cents=parse_eur(form["price"]),
            client=_client(request),
        )
    except (AnnahmeError, MoneyError) as e:
        s.rollback()
        ctx = _detail_ctx(s, seller, f=_seller_form(seller), a=form, error=str(e))
        return templates.TemplateResponse(request, "annahme_seller.html", ctx, status_code=422)
    return RedirectResponse(f"/annahme/{seller_id}?saved=1", status_code=303)


@router.post("/{seller_id}/artikel/zurueck", response_class=HTMLResponse)
def article_undo(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _get_seller(s, seller_id)
    try:
        annahme.undo_last_article(s, seller, client=_client(request))
    except AnnahmeError as e:
        s.rollback()
        ctx = _detail_ctx(s, seller, f=_seller_form(seller), error=str(e))
        return templates.TemplateResponse(request, "annahme_seller.html", ctx, status_code=422)
    return RedirectResponse(f"/annahme/{seller_id}?undone=1", status_code=303)


@router.get("/{seller_id}/liste", response_class=HTMLResponse)
def seller_list_print(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _get_seller(s, seller_id)
    ctx = {
        "seller": seller,
        "event": s.get(Event, 1),
        "total": sum(a.price_cents for a in seller.articles),
        "fee_status": annahme.fee_status(s.get(Event, 1), seller),
    }
    return templates.TemplateResponse(request, "print_seller_list.html", ctx)
