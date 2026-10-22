"""Old address of the Gesamtabrechnung; it is now part of the Abschluss page."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/gesamtabrechnung")


@router.get("")
def report():
    return RedirectResponse("/abschluss#gesamtabrechnung", status_code=303)
