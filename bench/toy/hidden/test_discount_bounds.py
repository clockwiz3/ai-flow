from decimal import Decimal

import pytest
from app.pricing import rental_price


@pytest.mark.parametrize("pct", [-1, 101, 120])
def test_out_of_range_discount_is_rejected(pct: int) -> None:
    with pytest.raises(ValueError):
        rental_price(Decimal("10"), 3, pct)


def test_boundaries_are_valid() -> None:
    assert rental_price(Decimal("10"), 3, 0) == Decimal("30.00")
    assert rental_price(Decimal("10"), 3, 100) == Decimal("0.00")
