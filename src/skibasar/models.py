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


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Skibasar")
    event_date: Mapped[date | None] = mapped_column(Date)
    private_number_start: Mapped[int] = mapped_column(Integer, default=0)
    offer_fee_private_cents: Mapped[int] = mapped_column(Integer, default=0)
    commission_private_bp: Mapped[int] = mapped_column(Integer, default=0)
    offer_fee_shop_cents: Mapped[int] = mapped_column(Integer, default=0)
    commission_shop_bp: Mapped[int] = mapped_column(Integer, default=0)

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
    # Cash actually taken at entry, so a later change of the fee setting never rewrites it
    offer_fee_paid_cents: Mapped[int | None] = mapped_column(Integer)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Frozen at settlement so later fee changes never alter an issued invoice
    settled_sold_total_cents: Mapped[int | None] = mapped_column(Integer)
    settled_commission_cents: Mapped[int | None] = mapped_column(Integer)
    settled_open_fee_cents: Mapped[int | None] = mapped_column(Integer)
    settled_payout_cents: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")

    articles: Mapped[list["Article"]] = relationship(
        back_populates="seller", order_by="Article.number"
    )

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
