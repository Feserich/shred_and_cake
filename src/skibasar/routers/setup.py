"""Settings and shop management screens (German UI)."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import admin_pin
from ..csv_import import parse_shop_csv, validate
from ..models import Article, Event, Seller, SellerType
from ..money import (
    MAX_COMMISSION_BP,
    MoneyError,
    format_eur,
    format_percent_bp,
    parse_eur,
    parse_percent_bp,
)
from ..services import admin_pin as admin_pin_service
from ..services import shops
from ..services.numbering import RangeError

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.filters["eur"] = format_eur

router = APIRouter()


def get_session(request: Request):
    with request.app.state.session_factory() as s:
        yield s


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


def _event_form(event: Event) -> dict:
    return {
        "name": event.name,
        "event_date": event.event_date.isoformat() if event.event_date else "",
        "private_number_start": event.private_number_start,
        "offer_fee_private": format_eur(event.offer_fee_private_cents, symbol=False),
        "commission_private": format_percent_bp(event.commission_private_bp).removesuffix(" %"),
        "offer_fee_shop": format_eur(event.offer_fee_shop_cents, symbol=False),
        "commission_shop": format_percent_bp(event.commission_shop_bp).removesuffix(" %"),
    }


def _pin_state(s: Session) -> str:
    """'env' (set by SKIBASAR_ADMIN_PIN, not changeable here), 'set' or 'none'."""
    if admin_pin() is not None:
        return "env"
    return "set" if s.get(Event, 1).admin_pin_hash else "none"


@router.get("/einstellungen", response_class=HTMLResponse)
def settings_page(
    request: Request, saved: int = 0, pin_saved: int = 0, s: Session = Depends(get_session)
):
    ctx = {
        "f": _event_form(s.get(Event, 1)),
        "saved": saved,
        "pin_saved": pin_saved,
        "pin_state": _pin_state(s),
        "error": None,
        "pin_error": None,
    }
    return templates.TemplateResponse(request, "setup.html", ctx)


@router.post("/einstellungen/admin-pin", response_class=HTMLResponse)
def admin_pin_save(
    request: Request,
    current_pin: str = Form(""),
    new_pin: str = Form(""),
    s: Session = Depends(get_session),
):
    try:
        admin_pin_service.set_pin(s, current=current_pin, new=new_pin, client=_client(request))
    except admin_pin_service.AdminPinError as e:
        s.rollback()
        ctx = {
            "f": _event_form(s.get(Event, 1)),
            "saved": 0,
            "pin_saved": 0,
            "pin_state": _pin_state(s),
            "error": None,
            "pin_error": str(e),
        }
        return templates.TemplateResponse(request, "setup.html", ctx, status_code=422)
    return RedirectResponse("/einstellungen?pin_saved=1", status_code=303)


@router.post("/einstellungen", response_class=HTMLResponse)
def settings_save(
    request: Request,
    name: str = Form(...),
    event_date: str = Form(""),
    private_number_start: str = Form("0"),
    offer_fee_private: str = Form("0"),
    commission_private: str = Form("0"),
    offer_fee_shop: str = Form("0"),
    commission_shop: str = Form("0"),
    s: Session = Depends(get_session),
):
    from datetime import date

    form = {k: v for k, v in locals().items() if k not in ("request", "s", "date")}
    try:
        if not private_number_start.strip().isdigit():
            raise MoneyError("Ungültige Startnummer")
        values = {
            "name": name.strip() or "Skibasar",
            "event_date": date.fromisoformat(event_date) if event_date else None,
            "private_number_start": int(private_number_start),
            "offer_fee_private_cents": parse_eur(offer_fee_private or "0"),
            "commission_private_bp": parse_percent_bp(commission_private or "0"),
            "offer_fee_shop_cents": parse_eur(offer_fee_shop or "0"),
            "commission_shop_bp": parse_percent_bp(commission_shop or "0"),
        }
        if min(values["offer_fee_private_cents"], values["offer_fee_shop_cents"]) < 0:
            raise MoneyError("Gebühren dürfen nicht negativ sein")
        if max(values["commission_private_bp"], values["commission_shop_bp"]) > MAX_COMMISSION_BP:
            raise MoneyError("Die Provision darf höchstens 100 % sein")
        if values["private_number_start"] > 0:
            used = s.scalar(
                select(func.min(Article.number))
                .join(Seller)
                .where(Seller.type == SellerType.private)
            )
            if used is not None and used < values["private_number_start"]:
                raise MoneyError("Es gibt bereits Privatartikel unterhalb der Startnummer")
    except (MoneyError, ValueError) as e:
        ctx = {
            "f": form,
            "saved": 0,
            "pin_saved": 0,
            "pin_state": _pin_state(s),
            "error": str(e),
            "pin_error": None,
        }
        return templates.TemplateResponse(request, "setup.html", ctx, status_code=422)
    shops.update_event(s, values, _client(request))
    return RedirectResponse("/einstellungen?saved=1", status_code=303)


def _shop_form(shop: Seller | None = None) -> dict:
    if shop is None:
        return {
            "name": "",
            "range_start": "",
            "range_end": "",
            "phone": "",
            "email": "",
            "fee_exempt": False,
            "offer_fee_paid_at_entry": False,
            "notes": "",
        }
    return {
        "name": shop.name,
        "range_start": shop.number_range_start,
        "range_end": shop.number_range_end,
        "phone": shop.phone,
        "email": shop.email,
        "fee_exempt": shop.fee_exempt,
        "notes": shop.notes,
        "offer_fee_paid_at_entry": shop.offer_fee_paid_at_entry,
    }


@router.get("/haendler", response_class=HTMLResponse)
def shop_list(request: Request, s: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "shops.html",
        {"shops": shops.list_shops(s), "f": _shop_form(), "action": "/haendler", "error": None},
    )


def _save_shop(request, s, shop, form, template, ctx):
    try:
        if not (form["range_start"].strip().isdigit() and form["range_end"].strip().isdigit()):
            raise RangeError("Nummernbereich muss aus Zahlen bestehen")
        saved = shops.save_shop(
            s,
            shop,
            name=form["name"],
            range_start=int(form["range_start"]),
            range_end=int(form["range_end"]),
            fee_exempt=form["fee_exempt"],
            offer_fee_paid_at_entry=form["offer_fee_paid_at_entry"],
            phone=form["phone"],
            email=form["email"],
            notes=form["notes"],
            client=_client(request),
        )
    except RangeError as e:
        s.rollback()
        return templates.TemplateResponse(
            request, template, {**ctx, "f": form, "error": str(e)}, status_code=422
        )
    return RedirectResponse(f"/haendler/{saved.id}", status_code=303)


async def _form_values(request: Request) -> dict:
    data = await request.form()
    text = {
        k: str(data.get(k, ""))
        for k in ("name", "range_start", "range_end", "phone", "email", "notes")
    }
    return {
        **text,
        "fee_exempt": "fee_exempt" in data,
        "offer_fee_paid_at_entry": "offer_fee_paid_at_entry" in data,
    }


@router.post("/haendler", response_class=HTMLResponse)
async def shop_create(request: Request, s: Session = Depends(get_session)):
    ctx = {"shops": shops.list_shops(s), "action": "/haendler"}
    return _save_shop(request, s, None, await _form_values(request), "shops.html", ctx)


def _get_shop(s: Session, shop_id: int) -> Seller:
    shop = s.get(Seller, shop_id)
    if shop is None or shop.type != SellerType.shop:
        raise HTTPException(404, "Händler nicht gefunden")
    return shop


def _detail_ctx(shop: Seller, message: str | None = None) -> dict:
    return {
        "shop": shop,
        "total": sum(a.price_cents for a in shop.articles),
        "action": f"/haendler/{shop.id}",
        "message": message,
    }


@router.get("/haendler/{shop_id}", response_class=HTMLResponse)
def shop_detail(
    request: Request, shop_id: int, imported: int = 0, s: Session = Depends(get_session)
):
    shop = _get_shop(s, shop_id)
    ctx = _detail_ctx(shop, "Import übernommen." if imported else None)
    return templates.TemplateResponse(
        request, "shop_detail.html", {**ctx, "f": _shop_form(shop), "error": None}
    )


@router.post("/haendler/{shop_id}", response_class=HTMLResponse)
async def shop_update(request: Request, shop_id: int, s: Session = Depends(get_session)):
    shop = _get_shop(s, shop_id)
    return _save_shop(
        request, s, shop, await _form_values(request), "shop_detail.html", _detail_ctx(shop)
    )


@router.post("/haendler/{shop_id}/import", response_class=HTMLResponse)
async def import_preview(
    request: Request, shop_id: int, file: UploadFile, s: Session = Depends(get_session)
):
    shop = _get_shop(s, shop_id)
    if shop.settled_at is not None:
        raise HTTPException(422, shops.SETTLED_IMPORT_MESSAGE)
    parsed = parse_shop_csv(await file.read())
    validate(parsed, shop.number_range_start, shop.number_range_end)
    diff = shops.diff_import(s, shop, parsed)
    token = secrets.token_urlsafe(16)
    pending = request.app.state.pending_imports
    pending[token] = (shop_id, parsed)
    while len(pending) > 20:  # keep memory bounded
        pending.pop(next(iter(pending)))
    can_commit = not (parsed.has_errors or diff.errors)
    return templates.TemplateResponse(
        request,
        "import_preview.html",
        {"shop": shop, "parsed": parsed, "diff": diff, "token": token, "can_commit": can_commit},
    )


@router.post("/haendler/{shop_id}/import/{token}")
def import_commit(request: Request, shop_id: int, token: str, s: Session = Depends(get_session)):
    shop = _get_shop(s, shop_id)
    if shop.settled_at is not None:
        raise HTTPException(422, shops.SETTLED_IMPORT_MESSAGE)
    entry = request.app.state.pending_imports.get(token)
    if entry is None or entry[0] != shop_id:
        raise HTTPException(410, "Vorschau abgelaufen – bitte die Datei erneut hochladen")
    try:
        shops.apply_import(s, shop, entry[1], _client(request))
    except RangeError as e:
        s.rollback()
        raise HTTPException(422, str(e)) from e
    request.app.state.pending_imports.pop(token, None)
    return RedirectResponse(f"/haendler/{shop_id}?imported=1", status_code=303)
