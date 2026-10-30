"""Rental price calculation."""

from decimal import ROUND_HALF_UP, Decimal


def rental_price(daily_rate: Decimal, days: int, discount_pct: int = 0) -> Decimal:
    """Total price for renting an item; weekly rentals (7+ days) get one free day per full week."""
    if days <= 0:
        raise ValueError("days must be positive")
    free_days = days // 7
    total = daily_rate * (days - free_days)
    total = total * (100 - discount_pct) / 100
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
