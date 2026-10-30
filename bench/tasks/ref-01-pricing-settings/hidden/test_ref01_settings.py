"""Pricing settings live in app/settings.py and are read by the services at call time."""

import ast
import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
import app.settings as settings_module
from app.clock import FixedClock
from app.models import CustomerTier
from app.settings import PRICING, PricingSettings

SERVICES = Path(app.__file__).resolve().parent / "services"

OLD_CONSTANTS = {
    "TAX_RATE",
    "MAX_TOTAL_DISCOUNT",
    "FREE_DAY_EVERY",
    "TIER_DISCOUNTS",
    "LATE_FEE_MULTIPLIER",
    "MAX_RENTAL_DAYS",
}
OLD_DECIMAL_LITERALS = {"0.2", "0.20", "0.3", "0.30", "1.5", "1.50", "0.05", "0.15"}
OLD_INT_LITERALS = {7, 90}


def _service_trees() -> list[tuple[str, ast.Module]]:
    files = sorted(SERVICES.glob("*.py"))
    assert files, SERVICES
    return [(f.name, ast.parse(f.read_text(encoding="utf-8"))) for f in files]


def test_settings_is_a_frozen_dataclass_with_current_defaults() -> None:
    assert dataclasses.is_dataclass(PricingSettings)
    assert isinstance(PRICING, PricingSettings)
    assert PRICING.tax_rate == Decimal("0.20")
    assert PRICING.max_total_discount == Decimal("0.30")
    assert PRICING.free_day_every == 7
    assert PRICING.late_fee_multiplier == Decimal("1.5")
    assert PRICING.max_rental_days == 90
    assert dict(PRICING.tier_discounts) == {
        CustomerTier.REGULAR: Decimal("0"),
        CustomerTier.SILVER: Decimal("0.05"),
        CustomerTier.GOLD: Decimal("0.15"),
    }
    for rate in (PRICING.tax_rate, PRICING.max_total_discount, PRICING.late_fee_multiplier):
        assert isinstance(rate, Decimal)
    assert all(isinstance(v, Decimal) for v in PRICING.tier_discounts.values())
    with pytest.raises(dataclasses.FrozenInstanceError):
        PRICING.tax_rate = Decimal("0.5")  # type: ignore[misc]


def test_default_instance_equals_fresh_defaults() -> None:
    fresh = PricingSettings()
    assert fresh.tax_rate == PRICING.tax_rate
    assert dict(fresh.tier_discounts) == dict(PRICING.tier_discounts)
    assert fresh.max_total_discount == PRICING.max_total_discount
    assert fresh.free_day_every == PRICING.free_day_every
    assert fresh.late_fee_multiplier == PRICING.late_fee_multiplier
    assert fresh.max_rental_days == PRICING.max_rental_days


def test_services_hold_no_copies_of_the_constants() -> None:
    for name, tree in _service_trees():
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assert target.id not in OLD_CONSTANTS, f"{name}: {target.id} still defined"
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    assert node.value.strip() not in OLD_DECIMAL_LITERALS, (
                        f"{name}: literal {node.value!r} duplicated from settings"
                    )
                elif isinstance(node.value, float):
                    raise AssertionError(f"{name}: float literal {node.value!r}")
                elif type(node.value) is int:
                    assert node.value not in OLD_INT_LITERALS, (
                        f"{name}: literal {node.value!r} duplicated from settings"
                    )


def _use(monkeypatch: pytest.MonkeyPatch, **changes) -> None:
    monkeypatch.setattr(settings_module, "PRICING", dataclasses.replace(PRICING, **changes))


def test_tax_rate_comes_from_settings(client: TestClient, monkeypatch) -> None:
    _use(monkeypatch, tax_rate=Decimal("0.10"))
    body = client.get("/reservations/4/invoice").json()
    assert (body["subtotal"], body["discount"], body["tax"], body["total"]) == (
        "54.00",
        "0.00",
        "5.40",
        "59.40",
    )


def test_tier_discounts_come_from_settings(client: TestClient, monkeypatch) -> None:
    tiers = dict(PRICING.tier_discounts)
    tiers[CustomerTier.GOLD] = Decimal("0.10")
    _use(monkeypatch, tier_discounts=tiers)
    body = client.get("/reservations/5/invoice").json()
    assert (body["subtotal"], body["discount"], body["tax"], body["total"]) == (
        "175.00",
        "17.50",
        "31.50",
        "189.00",
    )


def test_free_day_rule_comes_from_settings(client: TestClient, monkeypatch) -> None:
    _use(monkeypatch, free_day_every=5)
    line = client.get("/reservations/5/invoice").json()["lines"][0]
    assert line["quantity"] == 4
    assert line["description"] == "Family Tent rental (5 days, 1 free)"
    assert line["amount"] == "140.00"


def test_max_rental_days_comes_from_settings(client: TestClient, monkeypatch) -> None:
    _use(monkeypatch, max_rental_days=10)
    payload = {"item_id": 7, "customer_id": 1, "start": "2025-06-03", "end": "2025-06-14"}
    response = client.post("/reservations", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "Reservations are limited to 10 days"
    payload["end"] = "2025-06-13"
    assert client.post("/reservations", json=payload).status_code == 201


def test_late_fee_multiplier_comes_from_settings(
    client: TestClient, clock: FixedClock, monkeypatch
) -> None:
    _use(monkeypatch, late_fee_multiplier=Decimal("2"))
    clock.set(date(2025, 6, 8))
    receipt = client.post("/reservations/4/return", json={"returned_on": "2025-06-07"}).json()
    days_late = receipt["late_days"]
    assert days_late > 0
    assert Decimal(receipt["late_fee"]) == Decimal("36.00") * days_late
    lines = client.get("/reservations/4/invoice").json()["lines"]
    assert lines[1]["kind"] == "late_fee"
    assert Decimal(lines[1]["unit_price"]) == Decimal("36.00")


def test_default_settings_still_drive_defaults(client: TestClient, clock: FixedClock) -> None:
    clock.set(date(2025, 6, 8))
    receipt = client.post("/reservations/4/return", json={"returned_on": "2025-06-07"}).json()
    assert Decimal(receipt["late_fee"]) == Decimal("27.00") * receipt["late_days"]
