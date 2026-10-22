"""Abschluss: cake income, change money and expenditures -> final profit of the Basar."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Closing, Expense, ExpenseCategory
from . import audit, reports

CLOSING_FIELDS = (
    "cake_income_cents",
    "float_1_cents",
    "float_2_cents",
    "cash_1_cents",
    "cash_2_cents",
)


class AbschlussError(ValueError):
    """Invalid input; the message is shown to the user in German."""


@dataclass(frozen=True)
class Result:
    closing: Closing
    expenses: list[Expense]
    open_sellers: int
    club_income_cents: int  # commission + fees of the Basar
    bazaar_expenses_cents: int
    cake_income_cents: int
    cake_expenses_cents: int
    expected_cash_cents: int  # what the checkouts should hold if all cash flows were booked
    reconciles: bool  # the sales figures behind club_income_cents add up

    @property
    def bazaar_profit_cents(self) -> int:
        return self.club_income_cents - self.bazaar_expenses_cents

    @property
    def cake_profit_cents(self) -> int:
        return self.cake_income_cents - self.cake_expenses_cents

    @property
    def total_profit_cents(self) -> int:
        return self.bazaar_profit_cents + self.cake_profit_cents

    @property
    def float_cents(self) -> int:
        return self.closing.float_1_cents + self.closing.float_2_cents

    @property
    def counted_cash_cents(self) -> int | None:
        c = self.closing
        if c.cash_1_cents is None or c.cash_2_cents is None:
            return None
        return c.cash_1_cents + c.cash_2_cents

    @property
    def cash_difference_cents(self) -> int | None:
        counted = self.counted_cash_cents
        return None if counted is None else counted - self.expected_cash_cents


def get_closing(s: Session) -> Closing:
    closing = s.get(Closing, 1)
    if closing is None:
        closing = Closing(id=1)
        s.add(closing)
        s.flush()
    return closing


def save_closing(s: Session, values: dict[str, int | None], client: str = "") -> Closing:
    if set(values) != set(CLOSING_FIELDS):
        raise AbschlussError("Unvollständige Eingabe")
    if any(v is not None and v < 0 for v in values.values()):
        raise AbschlussError("Beträge dürfen nicht negativ sein")
    closing = get_closing(s)
    before = {k: getattr(closing, k) for k in CLOSING_FIELDS}
    for key, value in values.items():
        setattr(closing, key, value)
    audit.log(s, "closing", 1, "update", before, values, client)
    s.commit()
    return closing


def add_expense(
    s: Session,
    description: str,
    amount_cents: int,
    category: ExpenseCategory,
    paid_from_till: bool = False,
    client: str = "",
) -> Expense:
    description = description.strip()
    if not description:
        raise AbschlussError("Bitte beschreiben, wofür das Geld ausgegeben wurde")
    if amount_cents <= 0:
        raise AbschlussError("Der Betrag muss größer als 0 sein")
    expense = Expense(
        description=description,
        amount_cents=amount_cents,
        category=category,
        paid_from_till=paid_from_till,
    )
    s.add(expense)
    s.flush()
    audit.log(
        s,
        "expense",
        expense.id,
        "create",
        None,
        {
            "description": description,
            "amount_cents": amount_cents,
            "category": category.value,
            "paid_from_till": paid_from_till,
        },
        client,
    )
    s.commit()
    return expense


def delete_expense(s: Session, expense: Expense, client: str = "") -> None:
    before = {
        "description": expense.description,
        "amount_cents": expense.amount_cents,
        "category": expense.category.value,
        "paid_from_till": expense.paid_from_till,
    }
    audit.log(s, "expense", expense.id, "delete", before, None, client)
    s.delete(expense)
    s.commit()


def build(s: Session) -> Result:
    closing = get_closing(s)
    expenses = list(s.scalars(select(Expense).order_by(Expense.id)))
    report = reports.build(s)

    def total(category: ExpenseCategory) -> int:
        return sum(e.amount_cents for e in expenses if e.category == category)

    till_expenses = sum(e.amount_cents for e in expenses if e.paid_from_till)
    # Cash taken at checkout and at entry, minus payouts already made (negative = seller paid in)
    expected = (
        closing.float_1_cents
        + closing.float_2_cents
        + report.sales_total_cents
        + report.fee_at_entry_cents
        - report.payout_cents
        - till_expenses
    )
    return Result(
        closing=closing,
        expenses=expenses,
        open_sellers=len(report.open_sellers),
        club_income_cents=report.club_income_cents,
        bazaar_expenses_cents=total(ExpenseCategory.bazaar),
        cake_income_cents=closing.cake_income_cents,
        cake_expenses_cents=total(ExpenseCategory.cake),
        expected_cash_cents=expected,
        reconciles=report.reconciles,
    )
