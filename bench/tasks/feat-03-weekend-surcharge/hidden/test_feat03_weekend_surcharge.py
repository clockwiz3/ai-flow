from decimal import Decimal

from fastapi.testclient import TestClient

from app.clock import FixedClock

# Seed reminders (today is Monday 2025-06-02):
#   items: 1 Cordless Drill (tools, 12.00), 5 Two-Person Tent (camping, 20.00),
#          7 Sleeping Bag (camping, 8.00), 8 Camping Stove (camping, 6.50),
#          9 Mirrorless Camera (photo, 45.00), 10 Telephoto Lens (photo, 30.00)
#   customers: 1 regular, 2 silver, 3 gold, 4 regular; coupon WELCOME20 = 20%
#   reservation 5: Family Tent (camping), gold, 2025-06-10 .. 2025-06-15, active
# Calendar: 2025-06-07/08, 06-14/15, 06-21/22 are Saturday/Sunday.


def _set_pct(client: TestClient, category: str, pct: int):
    return client.put(f"/categories/{category}/pricing", json={"weekend_surcharge_pct": pct})


def _book(
    client: TestClient,
    item_id: int,
    customer_id: int,
    start: str,
    end: str,
    coupon_code: str | None = None,
) -> dict:
    payload = {"item_id": item_id, "customer_id": customer_id, "start": start, "end": end}
    if coupon_code is not None:
        payload["coupon_code"] = coupon_code
    response = client.post("/reservations", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _invoice(client: TestClient, reservation_id: int) -> dict:
    response = client.get(f"/reservations/{reservation_id}/invoice")
    assert response.status_code == 200, response.text
    return response.json()


def _line(line: dict) -> tuple:
    return (line["kind"], line["quantity"], Decimal(line["unit_price"]), Decimal(line["amount"]))


def _totals(invoice: dict) -> tuple:
    return tuple(Decimal(invoice[k]) for k in ("subtotal", "discount", "tax", "total"))


# --- pricing endpoints -------------------------------------------------------------------


def test_pricing_default_and_update(client: TestClient) -> None:
    response = client.get("/categories/photo/pricing")
    assert response.status_code == 200, response.text
    assert response.json() == {"category": "photo", "weekend_surcharge_pct": 0}

    updated = _set_pct(client, "photo", 20)
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"category": "photo", "weekend_surcharge_pct": 20}
    assert client.get("/categories/photo/pricing").json()["weekend_surcharge_pct"] == 20

    categories = {c["id"]: c for c in client.get("/categories").json()}
    assert categories["photo"]["weekend_surcharge_pct"] == 20
    assert categories["camping"]["weekend_surcharge_pct"] == 0
    assert categories["photo"]["name"] == "Photo & Video"

    assert _set_pct(client, "photo", 100).status_code == 200
    assert _set_pct(client, "photo", 0).status_code == 200
    assert client.get("/categories/photo/pricing").json()["weekend_surcharge_pct"] == 0


def test_pricing_validation(client: TestClient) -> None:
    unknown_get = client.get("/categories/boats/pricing")
    assert unknown_get.status_code == 404
    assert unknown_get.json()["code"] == "not_found"
    unknown_put = _set_pct(client, "boats", 10)
    assert unknown_put.status_code == 404
    assert unknown_put.json()["code"] == "not_found"

    _set_pct(client, "camping", 15)
    assert _set_pct(client, "camping", 101).status_code == 422
    assert _set_pct(client, "camping", -1).status_code == 422
    assert client.put("/categories/camping/pricing", json={}).status_code == 422
    assert client.get("/categories/camping/pricing").json()["weekend_surcharge_pct"] == 15


def test_reservation_snapshots_surcharge(client: TestClient) -> None:
    assert client.get("/reservations/5").json()["weekend_surcharge_pct"] == 0
    _set_pct(client, "photo", 20)
    first = _book(client, 9, 1, "2025-06-07", "2025-06-09")
    assert first["weekend_surcharge_pct"] == 20
    _set_pct(client, "photo", 50)
    assert client.get(f"/reservations/{first['id']}").json()["weekend_surcharge_pct"] == 20
    second = _book(client, 10, 1, "2025-06-07", "2025-06-09")
    assert second["weekend_surcharge_pct"] == 50
    drill = _book(client, 1, 1, "2025-06-07", "2025-06-09")
    assert drill["weekend_surcharge_pct"] == 0


# --- invoices ----------------------------------------------------------------------------


def test_weekday_only_rental_has_no_surcharge_line(client: TestClient) -> None:
    _set_pct(client, "photo", 20)
    # Monday 06-09 .. Saturday 06-14 (exclusive): Monday-Friday only.
    reservation = _book(client, 9, 1, "2025-06-09", "2025-06-14")
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 5, Decimal("45.00"), Decimal("225.00"))
    ]
    assert _totals(invoice) == (
        Decimal("225.00"),
        Decimal("0.00"),
        Decimal("45.00"),
        Decimal("270.00"),
    )


def test_zero_percent_category_has_no_surcharge_line(client: TestClient) -> None:
    _set_pct(client, "photo", 20)
    reservation = _book(client, 1, 1, "2025-06-07", "2025-06-09")
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 2, Decimal("12.00"), Decimal("24.00"))
    ]


def test_worked_example_with_capped_discount(client: TestClient) -> None:
    _set_pct(client, "photo", 20)
    # Sunday 06-08 .. Monday 06-16: 8 days, the 7th day (Saturday 06-14) is free.
    reservation = _book(client, 9, 3, "2025-06-08", "2025-06-16", "WELCOME20")
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 7, Decimal("45.00"), Decimal("315.00")),
        ("weekend_surcharge", 2, Decimal("9.00"), Decimal("18.00")),
    ]
    assert _totals(invoice) == (
        Decimal("333.00"),
        Decimal("99.90"),
        Decimal("46.62"),
        Decimal("279.72"),
    )


def test_free_seventh_day_on_a_sunday(client: TestClient) -> None:
    _set_pct(client, "camping", 25)
    # Monday 06-02 .. Monday 06-09: the 7th day is Sunday 06-08 and is free.
    reservation = _book(client, 5, 1, "2025-06-02", "2025-06-09")
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 6, Decimal("20.00"), Decimal("120.00")),
        ("weekend_surcharge", 1, Decimal("5.00"), Decimal("5.00")),
    ]
    assert _totals(invoice) == (
        Decimal("125.00"),
        Decimal("0.00"),
        Decimal("25.00"),
        Decimal("150.00"),
    )


def test_two_free_days_both_on_saturdays(client: TestClient) -> None:
    _set_pct(client, "photo", 10)
    # Sunday 06-08 .. Sunday 06-22: 14 days; free days are Saturdays 06-14 and 06-21.
    reservation = _book(client, 10, 2, "2025-06-08", "2025-06-22")
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 12, Decimal("30.00"), Decimal("360.00")),
        ("weekend_surcharge", 2, Decimal("3.00"), Decimal("6.00")),
    ]
    assert _totals(invoice) == (
        Decimal("366.00"),
        Decimal("18.30"),
        Decimal("69.54"),
        Decimal("417.24"),
    )


def test_surcharge_rounding_and_discount_base(client: TestClient) -> None:
    _set_pct(client, "camping", 15)
    # Saturday 06-07 .. Sunday 06-15: 8 days, the 7th day (Friday 06-13) is free;
    # weekend days 06-07, 06-08, 06-14 are surcharged.
    reservation = _book(client, 8, 2, "2025-06-07", "2025-06-15")
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 7, Decimal("6.50"), Decimal("45.50")),
        ("weekend_surcharge", 3, Decimal("0.975"), Decimal("2.93")),
    ]
    assert _totals(invoice) == (
        Decimal("48.43"),
        Decimal("2.42"),
        Decimal("9.20"),
        Decimal("55.21"),
    )


def test_late_fee_is_not_surcharged_or_discounted(
    client: TestClient, clock: FixedClock
) -> None:
    _set_pct(client, "camping", 25)
    # Monday 06-02 .. Saturday 06-07: weekdays only; returned two days late (Sat + Sun).
    reservation = _book(client, 5, 3, "2025-06-02", "2025-06-07")
    clock.set(clock.today().replace(day=10))
    returned = client.post(
        f"/reservations/{reservation['id']}/return", json={"returned_on": "2025-06-09"}
    )
    assert returned.status_code == 200, returned.text
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 5, Decimal("20.00"), Decimal("100.00")),
        ("late_fee", 2, Decimal("30.00"), Decimal("60.00")),
    ]
    assert _totals(invoice) == (
        Decimal("160.00"),
        Decimal("15.00"),
        Decimal("29.00"),
        Decimal("174.00"),
    )


def test_line_order_with_surcharge_and_late_fee(client: TestClient, clock: FixedClock) -> None:
    _set_pct(client, "camping", 50)
    reservation = _book(client, 7, 1, "2025-06-06", "2025-06-09")
    clock.set(clock.today().replace(day=12))
    client.post(f"/reservations/{reservation['id']}/return", json={"returned_on": "2025-06-10"})
    invoice = _invoice(client, reservation["id"])
    assert [_line(line) for line in invoice["lines"]] == [
        ("rental", 3, Decimal("8.00"), Decimal("24.00")),
        ("weekend_surcharge", 2, Decimal("4.00"), Decimal("8.00")),
        ("late_fee", 1, Decimal("12.00"), Decimal("12.00")),
    ]
    assert _totals(invoice) == (
        Decimal("44.00"),
        Decimal("0.00"),
        Decimal("8.80"),
        Decimal("52.80"),
    )


def test_pricing_change_does_not_affect_existing_reservations(client: TestClient) -> None:
    before = _book(client, 5, 1, "2025-06-07", "2025-06-09")
    _set_pct(client, "camping", 50)
    after = _book(client, 7, 1, "2025-06-07", "2025-06-09")

    assert [_line(line) for line in _invoice(client, before["id"])["lines"]] == [
        ("rental", 2, Decimal("20.00"), Decimal("40.00"))
    ]
    assert [_line(line) for line in _invoice(client, after["id"])["lines"]] == [
        ("rental", 2, Decimal("8.00"), Decimal("16.00")),
        ("weekend_surcharge", 2, Decimal("4.00"), Decimal("8.00")),
    ]
    # Seeded reservation 5 spans Saturday 06-14 but was booked at 0%.
    assert [_line(line) for line in _invoice(client, 5)["lines"]] == [
        ("rental", 5, Decimal("35.00"), Decimal("175.00"))
    ]


# --- reports -----------------------------------------------------------------------------


def test_revenue_report_includes_surcharges(client: TestClient) -> None:
    _set_pct(client, "photo", 20)
    _set_pct(client, "camping", 10)
    _book(client, 9, 1, "2025-06-07", "2025-06-09")  # 90.00 + 18.00
    _book(client, 7, 4, "2025-06-14", "2025-06-16")  # 16.00 + 1.60
    _book(client, 1, 1, "2025-06-21", "2025-06-23")  # tools, outside the period

    params = {"start": "2025-06-06", "end": "2025-06-20"}
    response = client.get("/reports/revenue", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == [
        {"category": "camping", "reservations": 2, "revenue": "166.35"},
        {"category": "photo", "reservations": 1, "revenue": "108.00"},
    ]
    assert body["total"] == "274.35"
