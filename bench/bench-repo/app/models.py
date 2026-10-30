"""Pydantic models and enums for the Rentwise domain.

Money values are ``Decimal`` everywhere and serialise to JSON strings (e.g. ``"12.50"``).
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ItemStatus(StrEnum):
    AVAILABLE = "available"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class CustomerTier(StrEnum):
    REGULAR = "regular"
    SILVER = "silver"
    GOLD = "gold"


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class InvoiceLineKind(StrEnum):
    RENTAL = "rental"
    LATE_FEE = "late_fee"


class DomainModel(BaseModel):
    """Base model: entities are immutable, updates go through ``model_copy``."""

    model_config = ConfigDict(frozen=True)


# --- catalog ---------------------------------------------------------------------------


class Category(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str


class ItemCreate(DomainModel):
    name: str = Field(min_length=1, max_length=120)
    category: str
    daily_rate: PositiveMoney
    deposit: Money
    status: ItemStatus = ItemStatus.AVAILABLE

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class Item(ItemCreate):
    id: int


class ItemStatusUpdate(DomainModel):
    status: ItemStatus


class ItemPage(DomainModel):
    items: list[Item]
    total: int
    limit: int
    offset: int


# --- customers -------------------------------------------------------------------------


class CustomerCreate(DomainModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    tier: CustomerTier = CustomerTier.REGULAR

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class Customer(CustomerCreate):
    id: int


# --- coupons ---------------------------------------------------------------------------


class CouponCreate(DomainModel):
    code: str = Field(min_length=3, max_length=20)
    percent: int = Field(ge=1, le=100, description="Percent off the rental subtotal.")

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalnum():
            raise ValueError("coupon code must be alphanumeric")
        return value


class Coupon(CouponCreate):
    pass


# --- reservations ----------------------------------------------------------------------


class ReservationCreate(DomainModel):
    item_id: int
    customer_id: int
    start: date
    end: date = Field(description="Exclusive: the item is back on the morning of this date.")
    coupon_code: str | None = None


class Reservation(DomainModel):
    id: int
    item_id: int
    customer_id: int
    start: date
    end: date
    status: ReservationStatus = ReservationStatus.ACTIVE
    coupon_code: str | None = None
    created_on: date
    returned_on: date | None = None
    damaged: bool = False

    @property
    def days(self) -> int:
        """Number of rental days (``end`` is exclusive)."""
        return (self.end - self.start).days


class ReturnRequest(DomainModel):
    returned_on: date | None = Field(default=None, description="Defaults to today when omitted.")
    damaged: bool = False


class ReturnReceipt(DomainModel):
    reservation_id: int
    returned_on: date
    late_days: int
    late_fee: Money
    damaged: bool
    deposit: Money
    deposit_refunded: Money
    deposit_withheld: Money


class Availability(DomainModel):
    item_id: int
    start: date
    end: date
    available: bool
    reason: str | None = None
    conflicting_reservation_ids: list[int] = Field(default_factory=list)


# --- invoices --------------------------------------------------------------------------


class InvoiceLine(DomainModel):
    kind: InvoiceLineKind
    description: str
    quantity: int
    unit_price: Decimal
    amount: Money


class Invoice(DomainModel):
    reservation_id: int
    customer_id: int
    lines: list[InvoiceLine]
    subtotal: Money
    discount: Money
    tax: Money
    total: Money


# --- reports ---------------------------------------------------------------------------


class CategoryRevenue(DomainModel):
    category: str
    reservations: int
    revenue: Money


class RevenueReport(DomainModel):
    start: date
    end: date
    rows: list[CategoryRevenue]
    total: Money


class ItemUtilization(DomainModel):
    item_id: int
    item_name: str
    reserved_days: int
    period_days: int
    utilization_pct: Decimal


class UtilizationReport(DomainModel):
    start: date
    end: date
    rows: list[ItemUtilization]
