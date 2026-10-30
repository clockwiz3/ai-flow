"""Rental pricing: billable days, tier and coupon discounts, coupons, money rounding."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.errors import ConflictError, NotFoundError
from app.models import Coupon, CouponCreate, Customer, CustomerTier, Item
from app.storage import Store

CENT = Decimal("0.01")
ZERO = Decimal("0")
TAX_RATE = Decimal("0.20")
MAX_TOTAL_DISCOUNT = Decimal("0.30")
FREE_DAY_EVERY = 7

TIER_DISCOUNTS: dict[CustomerTier, Decimal] = {
    CustomerTier.REGULAR: Decimal("0"),
    CustomerTier.SILVER: Decimal("0.05"),
    CustomerTier.GOLD: Decimal("0.15"),
}


def money(value: Decimal) -> Decimal:
    """Round a monetary amount to cents, half up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def rental_days(start: date, end: date) -> int:
    """Number of rental days in ``[start, end)``."""
    return (end - start).days


def free_days(days: int) -> int:
    """One free day for every full ``FREE_DAY_EVERY`` days."""
    return days // FREE_DAY_EVERY


def billable_days(days: int) -> int:
    return days - free_days(days)


@dataclass(frozen=True)
class DiscountBreakdown:
    """Discount rates (fractions, e.g. ``0.15``) applicable to a rental subtotal."""

    tier_rate: Decimal
    coupon_rate: Decimal

    @property
    def total_rate(self) -> Decimal:
        return self.tier_rate + self.coupon_rate


def resolve_discounts(tier: CustomerTier, coupon: Coupon | None = None) -> DiscountBreakdown:
    """Combine the customer's tier discount with an optional coupon.

    Discounts are additive and the combined rate is capped at ``MAX_TOTAL_DISCOUNT``.
    """
    tier_rate = TIER_DISCOUNTS[tier]
    coupon_rate = Decimal(coupon.percent) / 100 if coupon is not None else ZERO
    coupon_rate = min(coupon_rate, MAX_TOTAL_DISCOUNT)
    return DiscountBreakdown(tier_rate=tier_rate, coupon_rate=coupon_rate)


@dataclass(frozen=True)
class RentalQuote:
    """Price of the rental part of a reservation, before discounts and tax."""

    days: int
    free_days: int
    billable_days: int
    daily_rate: Decimal
    rental_amount: Decimal
    discounts: DiscountBreakdown


def quote_rental(
    item: Item,
    customer: Customer,
    start: date,
    end: date,
    coupon: Coupon | None = None,
) -> RentalQuote:
    days = rental_days(start, end)
    billable = billable_days(days)
    return RentalQuote(
        days=days,
        free_days=free_days(days),
        billable_days=billable,
        daily_rate=item.daily_rate,
        rental_amount=money(item.daily_rate * billable),
        discounts=resolve_discounts(customer.tier, coupon),
    )


# --- coupons ---------------------------------------------------------------------------


def list_coupons(store: Store) -> list[Coupon]:
    return store.coupons.all()


def lookup_coupon(store: Store, code: str) -> Coupon | None:
    """Find a coupon by code (case-insensitive)."""
    return store.coupons.get(code)


def get_coupon(store: Store, code: str) -> Coupon:
    coupon = lookup_coupon(store, code)
    if coupon is None:
        raise NotFoundError(f"Coupon {code!r} not found")
    return coupon


def create_coupon(store: Store, data: CouponCreate) -> Coupon:
    if data.code in store.coupons:
        raise ConflictError(f"Coupon {data.code!r} already exists")
    return store.coupons.create(data)
