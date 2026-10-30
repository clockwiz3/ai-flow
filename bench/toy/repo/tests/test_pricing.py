from decimal import Decimal

import pytest

from app.pricing import rental_price


def test_short_rental() -> None:
    assert rental_price(Decimal(10), 3) == Decimal("30.00")


def test_weekly_rental_gets_a_free_day() -> None:
    assert rental_price(Decimal(10), 7) == Decimal("60.00")


def test_days_must_be_positive() -> None:
    with pytest.raises(ValueError):
        rental_price(Decimal(10), 0)
