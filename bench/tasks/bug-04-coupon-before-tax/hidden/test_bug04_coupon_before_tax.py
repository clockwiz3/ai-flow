from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.clock import FixedClock


def _invoice(client: TestClient, reservation_id: int) -> dict:
    response = client.get(f"/reservations/{reservation_id}/invoice")
    assert response.status_code == 200, response.text
    return response.json()


def _figures(invoice: dict) -> tuple[str, str, str, str]:
    return invoice["subtotal"], invoice["discount"], invoice["tax"], invoice["total"]


def test_silver_with_coupon(client: TestClient, reserve) -> None:
    created = reserve(6, 2, "2025-06-20", "2025-06-25", coupon_code="SPRING10")
    assert _figures(_invoice(client, created["id"])) == ("175.00", "26.25", "29.75", "178.50")


def test_regular_with_coupon(client: TestClient, reserve) -> None:
    # Mirrorless Camera 45.00/day, 3 days = 135.00, 20% off before tax
    created = reserve(9, 1, "2025-06-20", "2025-06-23", coupon_code="WELCOME20")
    assert _figures(_invoice(client, created["id"])) == ("135.00", "27.00", "21.60", "129.60")


def test_silver_with_larger_coupon_and_free_day(client: TestClient, reserve) -> None:
    # Telephoto Lens 30.00/day, 7 days -> 6 billable = 180.00; 5% + 20% = 25%
    created = reserve(10, 2, "2025-06-20", "2025-06-27", coupon_code="WELCOME20")
    assert _figures(_invoice(client, created["id"])) == ("180.00", "45.00", "27.00", "162.00")


def test_coupon_does_not_discount_late_fee(
    client: TestClient, clock: FixedClock, reserve
) -> None:
    # Cordless Drill 12.00/day, 2 days = 24.00, regular customer, 10% coupon
    created = reserve(1, 1, "2025-06-02", "2025-06-04", coupon_code="SPRING10")
    clock.set(date(2025, 6, 7))
    assert client.post(f"/reservations/{created['id']}/return").status_code == 200

    invoice = _invoice(client, created["id"])
    rental = [line for line in invoice["lines"] if line["kind"] == "rental"][0]
    late = [line for line in invoice["lines"] if line["kind"] == "late_fee"][0]
    assert rental["amount"] == "24.00"
    late_amount = Decimal(late["amount"])
    assert late_amount > 0

    subtotal = Decimal("24.00") + late_amount
    discount = Decimal("2.40")
    tax = ((subtotal - discount) * Decimal("0.20")).quantize(Decimal("0.01"))
    assert Decimal(invoice["subtotal"]) == subtotal
    assert Decimal(invoice["discount"]) == discount
    assert Decimal(invoice["tax"]) == tax
    assert Decimal(invoice["total"]) == subtotal - discount + tax


def test_revenue_report_uses_pre_tax_coupon(client: TestClient, reserve) -> None:
    reserve(6, 2, "2025-06-20", "2025-06-25", coupon_code="SPRING10")
    body = client.get(
        "/reports/revenue", params={"start": "2025-06-20", "end": "2025-06-21"}
    ).json()
    assert body["rows"] == [{"category": "camping", "reservations": 1, "revenue": "148.75"}]


def test_invoices_without_coupon_unchanged(client: TestClient, reserve) -> None:
    gold = reserve(6, 5, "2025-06-20", "2025-06-25")
    assert _figures(_invoice(client, gold["id"])) == ("175.00", "26.25", "29.75", "178.50")
    silver = reserve(10, 2, "2025-06-20", "2025-06-27")
    assert _figures(_invoice(client, silver["id"])) == ("180.00", "9.00", "34.20", "205.20")
    # seeded reservation 4: regular, Circular Saw, 3 days
    assert _figures(_invoice(client, 4)) == ("54.00", "0.00", "10.80", "64.80")
