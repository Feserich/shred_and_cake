"""Abschluss (final settlement): change money, counted tills, expenditures and the profit."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..models import Event, Expense, ExpenseCategory
from ..money import MoneyError, format_eur, parse_eur
from ..services import abschluss
from ..services.abschluss import AbschlussError
from .setup import _client, get_session, templates

router = APIRouter(prefix="/abschluss")

# Form field -> (Closing column, may be left empty)
_CLOSING_FORM = {
    "float_1": ("float_1_cents", False),
    "float_2": ("float_2_cents", False),
    "cash_1": ("cash_1_cents", True),
    "cash_2": ("cash_2_cents", True),
}


def _closing_form(closing) -> dict:
    def fmt(cents):
        return "" if cents is None else format_eur(cents, symbol=False)

    return {field: fmt(getattr(closing, column)) for field, (column, _) in _CLOSING_FORM.items()}


def _page(
    request: Request,
    s: Session,
    *,
    closing_form=None,
    expense_form=None,
    error=None,
    expense_error=None,
    saved=False,
    status=200,
):
    r = abschluss.build(s)
    ctx = {
        "r": r,
        "event": s.get(Event, 1),
        "f": closing_form or _closing_form(r.closing),
        "e": expense_form or {"description": "", "amount": "", "category": "bazaar"},
        "error": error,
        "expense_error": expense_error,
        "saved": saved,
    }
    return templates.TemplateResponse(request, "abschluss.html", ctx, status_code=status)


@router.get("", response_class=HTMLResponse)
def page(request: Request, saved: int = 0, s: Session = Depends(get_session)):
    return _page(request, s, saved=bool(saved))


@router.post("", response_class=HTMLResponse)
async def save(request: Request, s: Session = Depends(get_session)):
    data = await request.form()
    form = {field: str(data.get(field, "")).strip() for field in _CLOSING_FORM}
    try:
        values = {}
        for field, (column, optional) in _CLOSING_FORM.items():
            values[column] = None if optional and not form[field] else parse_eur(form[field] or "0")
        abschluss.save_closing(s, values, _client(request))
    except (MoneyError, AbschlussError) as e:
        s.rollback()
        return _page(request, s, closing_form=form, error=str(e), status=422)
    return RedirectResponse("/abschluss?saved=1", status_code=303)


@router.post("/ausgaben", response_class=HTMLResponse)
async def add_expense(request: Request, s: Session = Depends(get_session)):
    data = await request.form()
    form = {
        "description": str(data.get("description", "")),
        "amount": str(data.get("amount", "")),
        "category": str(data.get("category", "bazaar")),
        "paid_from_till": "paid_from_till" in data,
    }
    try:
        category = ExpenseCategory(form["category"])
        abschluss.add_expense(
            s,
            form["description"],
            parse_eur(form["amount"]),
            category,
            form["paid_from_till"],
            _client(request),
        )
    except (MoneyError, AbschlussError, ValueError) as e:
        s.rollback()
        return _page(request, s, expense_form=form, expense_error=str(e), status=422)
    return RedirectResponse("/abschluss#ausgaben", status_code=303)


@router.post("/ausgaben/{expense_id}/loeschen")
def delete_expense(request: Request, expense_id: int, s: Session = Depends(get_session)):
    expense = s.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(404, "Ausgabe nicht gefunden")
    abschluss.delete_expense(s, expense, _client(request))
    return RedirectResponse("/abschluss#ausgaben", status_code=303)
