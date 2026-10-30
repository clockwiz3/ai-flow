from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models import Coupon, CustomerTier
from app.services.pricing import billable_days, free_days, money, resolve_discounts


@pytest.mark.parametrize(
    ("days", "free", "billable"),
    [(1, 0, 1), (6, 0, 6), (7, 1, 6), (13, 1, 12), (14, 2, 12), (21, 3, 18)],
)
def test_free_days(days: int, free: int, billable: int) -> None:
    assert free_days(days) == free
    assert billable_days(days) == billable


@pytest.mark.parametrize(
    ("raw", "rounded"),
    [("2.345", "2.35"), ("2.344", "2.34"), ("10", "10.00"), ("0.005", "0.01")],
)
def test_money_rounds_half_up(raw: str, rounded: str) -> None:
    assert money(Decimal(raw)) == Decimal(rounded)


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        (CustomerTier.REGULAR, Decimal("0")),
        (CustomerTier.SILVER, Decimal("0.05")),
        (CustomerTier.GOLD, Decimal("0.15")),
    ],
)
def test_tier_discounts(tier: CustomerTier, expected: Decimal) -> None:
    assert resolve_discounts(tier).total_rate == expected


def test_coupon_adds_to_tier_discount() -> None:
    discounts = resolve_discounts(CustomerTier.SILVER, Coupon(code="SPRING10", percent=10))
    assert discounts.tier_rate == Decimal("0.05")
    assert discounts.coupon_rate == Decimal("0.10")
    assert discounts.total_rate == Decimal("0.15")


def test_coupon_for_regular_customer() -> None:
    discounts = resolve_discounts(CustomerTier.REGULAR, Coupon(code="WELCOME20", percent=20))
    assert discounts.total_rate == Decimal("0.20")


def test_list_coupons(client: TestClient) -> None:
    assert client.get("/coupons").json() == [
        {"code": "SPRING10", "percent": 10},
        {"code": "WELCOME20", "percent": 20},
    ]


def test_create_coupon(client: TestClient) -> None:
    response = client.post("/coupons", json={"code": "summer5", "percent": 5})
    assert response.status_code == 201
    assert response.json() == {"code": "SUMMER5", "percent": 5}
    assert "SUMMER5" in [c["code"] for c in client.get("/coupons").json()]


def test_duplicate_coupon_rejected(client: TestClient) -> None:
    response = client.post("/coupons", json={"code": "spring10", "percent": 15})
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "AB", "percent": 10},
        {"code": "BAD-CODE", "percent": 10},
        {"code": "ZERO", "percent": 0},
        {"code": "TOOMUCH", "percent": 101},
    ],
)
def test_invalid_coupon_rejected(client: TestClient, payload: dict) -> None:
    assert client.post("/coupons", json=payload).status_code == 422
