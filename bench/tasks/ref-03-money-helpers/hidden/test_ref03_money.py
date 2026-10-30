"""Money helpers live in app/money.py and are the only place that rounds."""

from decimal import Decimal
from pathlib import Path

import pytest

import app
from app.money import apply_percent, to_money, to_percent

APP_DIR = Path(app.__file__).resolve().parent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("2.675"), "2.68"),
        (Decimal("2.665"), "2.67"),
        (Decimal("2.674999"), "2.67"),
        (Decimal("0.005"), "0.01"),
        (Decimal("0.004"), "0.00"),
        (Decimal("-1.005"), "-1.01"),
        (Decimal("10"), "10.00"),
        (Decimal("54.0000"), "54.00"),
        (7, "7.00"),
        ("3.145", "3.15"),
    ],
)
def test_to_money_rounds_half_up_to_cents(raw, expected: str) -> None:
    result = to_money(raw)
    assert isinstance(result, Decimal)
    assert str(result) == expected


@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [
        (Decimal("175.00"), Decimal("0.15"), "26.25"),
        (Decimal("54.00"), Decimal("0.20"), "10.80"),
        (Decimal("10.05"), Decimal("0.5"), "5.03"),
        (Decimal("10.04"), Decimal("0.5"), "5.02"),
        (Decimal("33.33"), Decimal("0.05"), "1.67"),
        (Decimal("19.99"), Decimal("0"), "0.00"),
        (Decimal("80.00"), Decimal("1"), "80.00"),
        (Decimal("117.00"), Decimal("0.05"), "5.85"),
    ],
)
def test_apply_percent_multiplies_by_a_fraction_and_rounds_once(
    amount: Decimal, rate: Decimal, expected: str
) -> None:
    result = apply_percent(amount, rate)
    assert isinstance(result, Decimal)
    assert str(result) == expected


def test_apply_percent_does_not_round_inputs_first() -> None:
    # 1.004 * 2.5 = 2.51; rounding the amount to 1.00 first would give 2.50
    assert apply_percent(Decimal("1.004"), Decimal("2.5")) == Decimal("2.51")
    # 0.333 * 0.015 = 0.004995 -> 0.00 (a single rounding step, not 0.005 -> 0.01)
    assert apply_percent(Decimal("0.333"), Decimal("0.015")) == Decimal("0.00")


@pytest.mark.parametrize(
    ("part", "whole", "expected"),
    [
        (5, 9, "55.6"),
        (1, 3, "33.3"),
        (2, 3, "66.7"),
        (1, 16, "6.3"),
        (1, 8, "12.5"),
        (0, 7, "0.0"),
        (3, 3, "100.0"),
        (3, 10, "30.0"),
    ],
)
def test_to_percent_rounds_half_up_to_one_decimal(part: int, whole: int, expected: str) -> None:
    result = to_percent(part, whole)
    assert isinstance(result, Decimal)
    assert str(result) == expected


def test_pricing_money_still_rounds_like_to_money() -> None:
    from app.services.pricing import money

    assert money(Decimal("2.675")) == Decimal("2.68")


def _python_sources() -> list[Path]:
    files = [p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts]
    assert files
    return files


def test_no_rounding_outside_money_module() -> None:
    money_module = APP_DIR / "money.py"
    for path in _python_sources():
        if path == money_module:
            continue
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(APP_DIR)
        assert ".quantize(" not in source, f"{rel} still rounds by itself"
        assert "rounding=" not in source, f"{rel} still rounds by itself"


def test_services_use_the_helpers() -> None:
    services = APP_DIR / "services"
    for name in ("invoices.py", "reports.py", "returns.py", "pricing.py"):
        source = (services / name).read_text(encoding="utf-8")
        uses = "app.money" in source or "from app import money" in source
        assert uses, f"{name} does not use app.money"
    invoices = (services / "invoices.py").read_text(encoding="utf-8")
    assert "apply_percent(" in invoices
    reports = (services / "reports.py").read_text(encoding="utf-8")
    assert "to_percent(" in reports
