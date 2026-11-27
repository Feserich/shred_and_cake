"""ORM models. Money columns are integer cents, rates integer basis points."""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SellerType(enum.StrEnum):
    private = "private"
    shop = "shop"


class ArticleStatus(enum.StrEnum):
    available = "available"
    sold = "sold"
    returned = "returned"
    withdrawn = "withdrawn"
    lost = "lost"  # lost/stolen at the Basar: the club reimburses the seller

    @property
    def label(self) -> str:
        """German name shown in pages, printouts and messages."""
        return _ARTICLE_STATUS_LABELS[self]


_ARTICLE_STATUS_LABELS = {
    ArticleStatus.available: "nicht verkauft",
    ArticleStatus.sold: "verkauft",
    ArticleStatus.returned: "zurückgegeben",
    ArticleStatus.withdrawn: "zurückgezogen",
    ArticleStatus.lost: "verloren",
}


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Skibasar")
    event_date: Mapped[date | None] = mapped_column(Date)
    private_number_start: Mapped[int] = mapped_column(Integer, default=1)
    offer_fee_private_cents: Mapped[int] = mapped_column(Integer, default=100)
    commission_private_bp: Mapped[int] = mapped_column(Integer, default=1000)
    offer_fee_shop_cents: Mapped[int] = mapped_column(Integer, default=0)
    commission_shop_bp: Mapped[int] = mapped_column(Integer, default=1000)
    # Salted hash of the admin PIN (see config.hash_pin); empty = none set in the app
    admin_pin_hash: Mapped[str] = mapped_column(String(200), default="")

    def offer_fee_cents(self, seller_type: "SellerType") -> int:
        if seller_type == SellerType.shop:
            return self.offer_fee_shop_cents
        return self.offer_fee_private_cents


class Seller(Base):
    __tablename__ = "seller"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[SellerType] = mapped_column(Enum(SellerType), default=SellerType.private)
    name: Mapped[str] = mapped_column(String(200))
    first_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(400), default="")
    number_range_start: Mapped[int | None] = mapped_column(Integer)
    number_range_end: Mapped[int | None] = mapped_column(Integer)
    fee_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    offer_fee_paid_at_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    # Cash actually taken at entry (per article for private sellers; see fee_units),
    # so a later change of the fee setting never rewrites it
    offer_fee_paid_cents: Mapped[int | None] = mapped_column(Integer)
    # Articles the entry fee was paid for; None = all of them (also articles added later)
    offer_fee_paid_units: Mapped[int | None] = mapped_column(Integer)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Frozen at settlement so later fee changes never alter an issued invoice
    settled_sold_total_cents: Mapped[int | None] = mapped_column(Integer)
    settled_lost_total_cents: Mapped[int | None] = mapped_column(Integer)
    settled_commission_cents: Mapped[int | None] = mapped_column(Integer)
    settled_open_fee_cents: Mapped[int | None] = mapped_column(Integer)
    settled_payout_cents: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Mail the article list when the volunteer leaves the Annahme page (if mail is set up)
    annahme_mail: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    # Fingerprint of the last mailed article list: unchanged lists are not mailed again
    annahme_mail_sig: Mapped[str] = mapped_column(String(64), default="", server_default="")

    articles: Mapped[list["Article"]] = relationship(
        back_populates="seller", order_by="Article.number"
    )

    @property
    def fee_units(self) -> int:
        """How often the offer fee is charged: per article for private sellers, else once."""
        return len(self.articles) if self.type == SellerType.private else 1

    @property
    def fee_units_paid(self) -> int:
        """Fee units already paid in cash at entry."""
        if not self.offer_fee_paid_at_entry:
            return 0
        units = self.fee_units
        return units if self.offer_fee_paid_units is None else min(self.offer_fee_paid_units, units)

    @property
    def fee_units_open(self) -> int:
        """Fee units still to be paid (at entry or deducted at settlement)."""
        return 0 if self.fee_exempt else self.fee_units - self.fee_units_paid

    @property
    def fee_cash_at_entry_cents(self) -> int:
        """Cash taken at entry; stays counted when an article it covered is removed later."""
        if not self.offer_fee_paid_at_entry:
            return 0
        units = self.fee_units if self.offer_fee_paid_units is None else self.offer_fee_paid_units
        return (self.offer_fee_paid_cents or 0) * units

    def offer_fee_cents(self, event: "Event") -> int:
        """Fee per unit: once paid at entry, the seller keeps that rate for the rest as well."""
        if self.offer_fee_paid_at_entry and self.offer_fee_paid_cents is not None:
            return self.offer_fee_paid_cents
        return event.offer_fee_cents(self.type)

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.name}".strip()


class Sale(Base):
    __tablename__ = "sale"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    total_cents: Mapped[int] = mapped_column(Integer)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    articles: Mapped[list["Article"]] = relationship(back_populates="sale")
    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", order_by="SaleItem.number", cascade="all, delete-orphan"
    )


class SaleItem(Base):
    """An article as it was sold; survives a Storno, when the article itself is freed again."""

    __tablename__ = "sale_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sale.id"), index=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id"))
    number: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    price_cents: Mapped[int] = mapped_column(Integer)

    sale: Mapped[Sale] = relationship(back_populates="items")


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("seller.id"))
    description: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[str] = mapped_column(String(100), default="")
    color: Mapped[str] = mapped_column(String(100), default="")
    price_cents: Mapped[int] = mapped_column(Integer)
    shop_ref: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[ArticleStatus] = mapped_column(
        Enum(ArticleStatus), default=ArticleStatus.available
    )
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sale.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    seller: Mapped[Seller] = relationship(back_populates="articles")
    sale: Mapped[Sale | None] = relationship(back_populates="articles")


class Closing(Base):
    """Inputs of the final settlement (Abschluss) that are not derived from sales (single row)."""

    __tablename__ = "closing"

    id: Mapped[int] = mapped_column(primary_key=True)
    # No longer used: the cake income is now derived from counting the cake till (cash_2)
    cake_income_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Change money (Wechselgeld); it belongs to the club and is no profit.
    # Till 1 is the Basar checkout (also Annahme fees and Abholung payouts), till 2 the cake sale.
    float_1_cents: Mapped[int] = mapped_column(Integer, default=0)
    float_2_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Counted cash at the end including the float; None = not counted yet
    cash_1_cents: Mapped[int | None] = mapped_column(Integer)
    cash_2_cents: Mapped[int | None] = mapped_column(Integer)


class ExpenseCategory(enum.StrEnum):
    bazaar = "bazaar"
    cake = "cake"


class Expense(Base):
    """An expenditure for organising the Basar or the cake sale."""

    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer)
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory), default=ExpenseCategory.bazaar
    )
    # Paid in cash out of the till of its category (Basar or cake), which then holds less money
    paid_from_till: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    client: Mapped[str] = mapped_column(String(100), default="")
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(50))
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")


class MailSecurity(enum.StrEnum):
    starttls = "starttls"  # usually port 587
    ssl = "ssl"  # usually port 465
    none = "none"  # unencrypted, only for local test servers


class MailSettings(Base):
    """Optional SMTP account for confirmation mails to sellers (single row, id 1)."""

    __tablename__ = "mail_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    host: Mapped[str] = mapped_column(String(200), default="")
    port: Mapped[int] = mapped_column(Integer, default=587)
    security: Mapped[MailSecurity] = mapped_column(
        Enum(MailSecurity), default=MailSecurity.starttls
    )
    username: Mapped[str] = mapped_column(String(200), default="")
    # Stored as given: SMTP needs the clear password (use an app password where possible)
    password: Mapped[str] = mapped_column(String(200), default="")
    sender_email: Mapped[str] = mapped_column(String(200), default="")
    sender_name: Mapped[str] = mapped_column(String(200), default="")

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender_email)

    @property
    def active(self) -> bool:
        return self.enabled and self.configured


class MailKind(enum.StrEnum):
    annahme = "annahme"
    abholung = "abholung"
    test = "test"

    @property
    def label(self) -> str:
        return {"annahme": "Annahme", "abholung": "Abrechnung", "test": "Test"}[self.value]


class MailStatus(enum.StrEnum):
    pending = "pending"  # waiting to be sent (e.g. no internet)
    sent = "sent"
    failed = "failed"  # rejected by the server; sent again only on request

    @property
    def label(self) -> str:
        return {"pending": "wartet", "sent": "gesendet", "failed": "fehlgeschlagen"}[self.value]


class OutgoingMail(Base):
    """Mail queue: content is frozen when queued, a background thread sends it when online."""

    __tablename__ = "mail_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("seller.id"), index=True)
    kind: Mapped[MailKind] = mapped_column(Enum(MailKind))
    recipient: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[MailStatus] = mapped_column(Enum(MailStatus), default=MailStatus.pending)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
