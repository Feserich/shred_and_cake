"""Overview tables with audited manual edits."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Article, Seller
from ..money import PRICE_WARN_CENTS, MoneyError, parse_eur
from ..services import uebersicht
from ..services.uebersicht import UebersichtError
from .setup import _client, get_session, templates

router = APIRouter(prefix="/uebersicht")


@router.get("")
def index():
    return RedirectResponse("/uebersicht/verkaeufer", status_code=303)


@router.get("/verkaeufer", response_class=HTMLResponse)
def sellers(
    request: Request,
    q: str = "",
    art: str = "",
    status: str = "",
    s: Session = Depends(get_session),
):
    ctx = {
        "tab": "verkaeufer",
        "rows": uebersicht.list_sellers(s, q, art, status),
        "q": q,
        "art": art,
        "status": status,
        "limit": uebersicht.LIMIT,
    }
    return templates.TemplateResponse(request, "uebersicht_verkaeufer.html", ctx)


@router.get("/artikel", response_class=HTMLResponse)
def articles(request: Request, q: str = "", status: str = "", s: Session = Depends(get_session)):
    ctx = {
        "tab": "artikel",
        "rows": uebersicht.list_articles(s, q, status),
        "q": q,
        "status": status,
        "limit": uebersicht.LIMIT,
    }
    return templates.TemplateResponse(request, "uebersicht_artikel.html", ctx)


@router.get("/verkaeufe", response_class=HTMLResponse)
def sales(request: Request, status: str = "", s: Session = Depends(get_session)):
    ctx = {
        "tab": "verkaeufe",
        "rows": uebersicht.list_sales(s, status),
        "status": status,
        "limit": uebersicht.LIMIT,
    }
    return templates.TemplateResponse(request, "uebersicht_verkaeufe.html", ctx)


@router.get("/protokoll", response_class=HTMLResponse)
def audit_log(request: Request, entity: str = "", s: Session = Depends(get_session)):
    ctx = {
        "tab": "protokoll",
        "rows": uebersicht.list_audit(s, entity),
        "entity": entity,
        "limit": uebersicht.LIMIT,
    }
    return templates.TemplateResponse(request, "uebersicht_protokoll.html", ctx)


def _seller(s: Session, seller_id: int) -> Seller:
    seller = s.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(404, "Verkäufer nicht gefunden")
    return seller


def _article(s: Session, number: int) -> Article:
    article = s.scalar(select(Article).where(Article.number == number))
    if article is None:
        raise HTTPException(404, "Artikel nicht gefunden")
    return article


def _seller_form(request: Request, seller: Seller, *, error=None, saved=False, status=200):
    ctx = {"tab": "verkaeufer", "seller": seller, "error": error, "saved": saved}
    return templates.TemplateResponse(
        request, "uebersicht_verkaeufer_edit.html", ctx, status_code=status
    )


def _article_form(
    request: Request, article: Article, *, error=None, saved=False, status=200, price_warning=None
):
    ctx = {
        "tab": "artikel",
        "a": article,
        "error": error,
        "saved": saved,
        "price_warning": price_warning,
    }
    return templates.TemplateResponse(
        request, "uebersicht_artikel_edit.html", ctx, status_code=status
    )


@router.get("/verkaeufer/{seller_id}", response_class=HTMLResponse)
def seller_edit(
    request: Request, seller_id: int, saved: int = 0, s: Session = Depends(get_session)
):
    return _seller_form(request, _seller(s, seller_id), saved=bool(saved))


@router.post("/verkaeufer/{seller_id}", response_class=HTMLResponse)
async def seller_save(request: Request, seller_id: int, s: Session = Depends(get_session)):
    seller = _seller(s, seller_id)
    f = await request.form()
    try:
        uebersicht.update_seller(
            s,
            seller,
            values={
                k: str(f.get(k, ""))
                for k in ("name", "first_name", "phone", "email", "address", "notes")
            },
            fee_exempt=f.get("fee_exempt") is not None,
            offer_fee_paid_at_entry=f.get("offer_fee_paid_at_entry") is not None,
            admin_pin_given=str(f.get("admin_pin", "")),
            client=_client(request),
        )
    except UebersichtError as e:
        s.rollback()
        s.refresh(seller)
        return _seller_form(request, seller, error=str(e), status=422)
    return RedirectResponse(f"/uebersicht/verkaeufer/{seller_id}?saved=1", status_code=303)


@router.get("/artikel/{number}", response_class=HTMLResponse)
def article_edit(request: Request, number: int, saved: int = 0, s: Session = Depends(get_session)):
    return _article_form(request, _article(s, number), saved=bool(saved))


@router.post("/artikel/{number}", response_class=HTMLResponse)
async def article_save(request: Request, number: int, s: Session = Depends(get_session)):
    article = _article(s, number)
    f = await request.form()
    try:
        try:
            price = parse_eur(str(f.get("price", "")))
        except MoneyError as e:
            raise UebersichtError("Der Preis ist nicht lesbar") from e
        if price > PRICE_WARN_CENTS and price != article.price_cents and "price_ok" not in f:
            return _article_form(request, article, price_warning=price)
        uebersicht.update_article(
            s,
            article,
            values={k: str(f.get(k, "")) for k in ("description", "brand", "size", "color")},
            price_cents=price,
            status=str(f.get("status", "")),
            admin_pin_given=str(f.get("admin_pin", "")),
            client=_client(request),
        )
    except UebersichtError as e:
        s.rollback()
        s.refresh(article)
        return _article_form(request, article, error=str(e), status=422)
    return RedirectResponse(f"/uebersicht/artikel/{number}?saved=1", status_code=303)
