from decimal import Decimal

from fastapi.testclient import TestClient

from app.clock import FixedClock

# Seed reminders (today is 2025-06-02):
#   items: 1 Cordless Drill 12.00, 2 Circular Saw 18.00 (reserved 06-01..06-04),
#          3 Rotary Hammer 25.00, 4 Tile Cutter (maintenance), 5 Two-Person Tent 20.00,
#          6 Family Tent 35.00 (reserved 06-10..06-15), 7 Sleeping Bag 8.00,
#          8 Camping Stove 6.50, 9 Mirrorless Camera 45.00, 10 Telephoto Lens 30.00
#          (cancelled reservation 06-05..06-08), 12 Lawn Aerator (retired)
#   customers: 1 regular, 2 silver (5%), 3 gold (15%); coupons SPRING10, WELCOME20


def _post_booking(
    client: TestClient,
    customer_id: int,
    items: list[int],
    start: str,
    end: str,
    coupon_code: str | None = None,
):
    payload: dict = {"customer_id": customer_id, "items": items, "start": start, "end": end}
    if coupon_code is not None:
        payload["coupon_code"] = coupon_code
    return client.post("/bookings", json=payload)


def _book(client: TestClient, *args, **kwargs) -> dict:
    response = _post_booking(client, *args, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def _json(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


def _lines(invoice: dict) -> list[tuple]:
    return [
        (line["kind"], line["quantity"], Decimal(line["unit_price"]), Decimal(line["amount"]))
        for line in invoice["lines"]
    ]


def _totals(invoice: dict) -> tuple:
    return tuple(Decimal(invoice[k]) for k in ("subtotal", "discount", "tax", "total"))


def _reservation_count(client: TestClient) -> int:
    return len(client.get("/reservations").json())


# --- creation ----------------------------------------------------------------------------


def test_create_booking(client: TestClient) -> None:
    booking = _book(client, 2, [9, 10, 1], "2025-06-09", "2025-06-12", "spring10")
    assert isinstance(booking["id"], int) and booking["id"] > 0
    assert booking["customer_id"] == 2
    assert booking["start"] == "2025-06-09"
    assert booking["end"] == "2025-06-12"
    assert booking["coupon_code"] == "SPRING10"
    assert booking["status"] == "active"
    ids = booking["reservation_ids"]
    assert len(ids) == 3 and ids == sorted(ids) and len(set(ids)) == 3

    for reservation_id, item_id in zip(ids, [9, 10, 1], strict=True):
        reservation = _json(client.get(f"/reservations/{reservation_id}"))
        assert reservation["item_id"] == item_id
        assert reservation["customer_id"] == 2
        assert reservation["booking_id"] == booking["id"]
        assert reservation["coupon_code"] == "SPRING10"
        assert reservation["status"] == "active"
        assert (reservation["start"], reservation["end"]) == ("2025-06-09", "2025-06-12")

    assert _json(client.get(f"/bookings/{booking['id']}")) == booking

    other = _book(client, 1, [3], "2025-06-09", "2025-06-12")
    assert other["id"] != booking["id"]
    assert other["coupon_code"] is None
    assert len(other["reservation_ids"]) == 1


def test_standalone_reservations_have_no_booking(client: TestClient) -> None:
    assert _json(client.get("/reservations/5"))["booking_id"] is None
    created = client.post(
        "/reservations",
        json={"item_id": 1, "customer_id": 1, "start": "2025-06-09", "end": "2025-06-10"},
    )
    assert created.status_code == 201
    assert created.json()["booking_id"] is None


def test_all_or_nothing(client: TestClient) -> None:
    before = _reservation_count(client)
    # 06-09..06-16 fully contains reservation 5 of item 6; item 4 is in maintenance.
    response = _post_booking(client, 1, [9, 6, 4, 1], "2025-06-09", "2025-06-16")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "conflict"
    assert body["unavailable_item_ids"] == [4, 6]
    assert isinstance(body["detail"], str) and body["detail"]
    assert _reservation_count(client) == before

    partial = _post_booking(client, 1, [3, 12, 2], "2025-06-03", "2025-06-05")
    assert partial.status_code == 409
    assert partial.json()["unavailable_item_ids"] == [2, 12]
    assert _reservation_count(client) == before

    _book(client, 1, [9, 1], "2025-06-09", "2025-06-16")
    assert _reservation_count(client) == before + 2
    availability = client.get(
        "/availability", params={"item_id": 9, "start": "2025-06-10", "end": "2025-06-11"}
    ).json()
    assert availability["available"] is False


def test_overlap_with_other_booking(client: TestClient) -> None:
    _book(client, 1, [9, 10], "2025-06-09", "2025-06-12")
    response = _post_booking(client, 2, [1, 10, 3], "2025-06-11", "2025-06-13")
    assert response.status_code == 409
    assert response.json()["unavailable_item_ids"] == [10]


def test_touching_and_cancelled_reservations_do_not_block(client: TestClient) -> None:
    _book(client, 1, [6], "2025-06-15", "2025-06-17")
    _book(client, 1, [10, 2], "2025-06-05", "2025-06-08")


def test_validation(client: TestClient) -> None:
    before = _reservation_count(client)

    duplicate = _post_booking(client, 1, [1, 3, 1], "2025-06-09", "2025-06-10")
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "invalid_request"
    assert _post_booking(client, 1, [], "2025-06-09", "2025-06-10").status_code == 422

    for start, end in [
        ("2025-06-10", "2025-06-10"),
        ("2025-06-01", "2025-06-03"),
        ("2025-06-09", "2025-09-08"),
    ]:
        bad = _post_booking(client, 1, [1], start, end)
        assert bad.status_code == 422, (start, end)
        assert bad.json()["code"] == "invalid_request"

    unknown_customer = _post_booking(client, 999, [1], "2025-06-09", "2025-06-10")
    assert unknown_customer.status_code == 404
    assert unknown_customer.json()["code"] == "not_found"

    unknown_coupon = _post_booking(client, 1, [1], "2025-06-09", "2025-06-10", "NOPE99")
    assert unknown_coupon.status_code == 422
    assert unknown_coupon.json()["code"] == "invalid_request"

    unknown_item = _post_booking(client, 1, [1, 999], "2025-06-09", "2025-06-10")
    assert unknown_item.status_code == 404
    assert unknown_item.json()["code"] == "not_found"
    unknown_and_unavailable = _post_booking(client, 1, [4, 999], "2025-06-09", "2025-06-10")
    assert unknown_and_unavailable.status_code == 404

    assert _reservation_count(client) == before


def test_unknown_booking(client: TestClient) -> None:
    for response in [
        client.get("/bookings/999"),
        client.post("/bookings/999/cancel"),
        client.get("/bookings/999/invoice"),
    ]:
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


# --- invoices ----------------------------------------------------------------------------


def test_booking_invoice_with_bundle_discount(client: TestClient) -> None:
    booking = _book(client, 2, [9, 10, 1], "2025-06-09", "2025-06-12", "SPRING10")
    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    assert invoice["booking_id"] == booking["id"]
    assert invoice["customer_id"] == 2
    assert _lines(invoice) == [
        ("rental", 3, Decimal("45.00"), Decimal("135.00")),
        ("rental", 3, Decimal("30.00"), Decimal("90.00")),
        ("rental", 3, Decimal("12.00"), Decimal("36.00")),
    ]
    # silver 5% + SPRING10 10% + bundle 5% = 20%
    assert _totals(invoice) == (
        Decimal("261.00"),
        Decimal("52.20"),
        Decimal("41.76"),
        Decimal("250.56"),
    )

    camera = _json(client.get(f"/reservations/{booking['reservation_ids'][0]}/invoice"))
    assert _totals(camera) == (
        Decimal("135.00"),
        Decimal("27.00"),
        Decimal("21.60"),
        Decimal("129.60"),
    )


def test_two_items_get_no_bundle_discount(client: TestClient) -> None:
    booking = _book(client, 2, [9, 10], "2025-06-09", "2025-06-12", "SPRING10")
    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    assert _totals(invoice) == (
        Decimal("225.00"),
        Decimal("33.75"),
        Decimal("38.25"),
        Decimal("229.50"),
    )


def test_bundle_discount_respects_cap(client: TestClient) -> None:
    booking = _book(client, 3, [9, 10, 1], "2025-06-09", "2025-06-12", "WELCOME20")
    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    # gold 15% + WELCOME20 20% + bundle 5% = 40%, capped at 30%
    assert _totals(invoice) == (
        Decimal("261.00"),
        Decimal("78.30"),
        Decimal("36.54"),
        Decimal("219.24"),
    )
    lens = _json(client.get(f"/reservations/{booking['reservation_ids'][1]}/invoice"))
    assert _totals(lens) == (
        Decimal("90.00"),
        Decimal("27.00"),
        Decimal("12.60"),
        Decimal("75.60"),
    )


def test_booking_discount_is_rounded_once(client: TestClient) -> None:
    created = client.post(
        "/items",
        json={"name": "Lantern", "category": "camping", "daily_rate": "9.90", "deposit": "10.00"},
    )
    assert created.status_code == 201, created.text
    lantern = created.json()["id"]
    booking = _book(client, 1, [8, lantern, 1], "2025-06-09", "2025-06-10")
    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    assert _lines(invoice) == [
        ("rental", 1, Decimal("6.50"), Decimal("6.50")),
        ("rental", 1, Decimal("9.90"), Decimal("9.90")),
        ("rental", 1, Decimal("12.00"), Decimal("12.00")),
    ]
    # 5% of 28.40 = 1.42 (not 0.33 + 0.50 + 0.60 = 1.43)
    assert _totals(invoice) == (
        Decimal("28.40"),
        Decimal("1.42"),
        Decimal("5.40"),
        Decimal("32.38"),
    )


def test_cancelling_one_reservation_drops_bundle(client: TestClient) -> None:
    booking = _book(client, 2, [9, 10, 1], "2025-06-09", "2025-06-12", "SPRING10")
    camera_id, _, drill_id = booking["reservation_ids"]
    cancelled = client.post(f"/reservations/{drill_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert _json(client.get(f"/bookings/{booking['id']}"))["status"] == "active"

    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    assert _lines(invoice) == [
        ("rental", 3, Decimal("45.00"), Decimal("135.00")),
        ("rental", 3, Decimal("30.00"), Decimal("90.00")),
    ]
    assert _totals(invoice) == (
        Decimal("225.00"),
        Decimal("33.75"),
        Decimal("38.25"),
        Decimal("229.50"),
    )
    camera = _json(client.get(f"/reservations/{camera_id}/invoice"))
    assert _totals(camera) == (
        Decimal("135.00"),
        Decimal("20.25"),
        Decimal("22.95"),
        Decimal("137.70"),
    )
    assert client.get(f"/reservations/{drill_id}/invoice").status_code == 409


def test_late_fee_in_booking_invoice(client: TestClient, clock: FixedClock) -> None:
    booking = _book(client, 1, [5, 7, 8], "2025-06-02", "2025-06-05")
    tent_id, bag_id, stove_id = booking["reservation_ids"]
    clock.set(clock.today().replace(day=8))
    late = client.post(f"/reservations/{bag_id}/return", json={"returned_on": "2025-06-07"})
    assert late.status_code == 200, late.text
    on_time = client.post(f"/reservations/{tent_id}/return", json={"returned_on": "2025-06-05"})
    assert on_time.status_code == 200, on_time.text

    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    assert _lines(invoice) == [
        ("rental", 3, Decimal("20.00"), Decimal("60.00")),
        ("rental", 3, Decimal("8.00"), Decimal("24.00")),
        ("late_fee", 2, Decimal("12.00"), Decimal("24.00")),
        ("rental", 3, Decimal("6.50"), Decimal("19.50")),
    ]
    # bundle 5% of the rental lines only (103.50), the late fee is not discounted
    assert _totals(invoice) == (
        Decimal("127.50"),
        Decimal("5.18"),
        Decimal("24.46"),
        Decimal("146.78"),
    )
    assert _json(client.get(f"/bookings/{booking['id']}"))["status"] == "active"


# --- cancellation ------------------------------------------------------------------------


def test_cancel_booking(client: TestClient) -> None:
    booking = _book(client, 1, [5, 7], "2025-06-09", "2025-06-12")
    response = client.post(f"/bookings/{booking['id']}/cancel")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["reservation_ids"] == booking["reservation_ids"]
    for reservation_id in booking["reservation_ids"]:
        assert _json(client.get(f"/reservations/{reservation_id}"))["status"] == "cancelled"

    again = client.post(f"/bookings/{booking['id']}/cancel")
    assert again.status_code == 409
    assert again.json()["code"] == "conflict"
    invoice = client.get(f"/bookings/{booking['id']}/invoice")
    assert invoice.status_code == 409
    assert invoice.json()["code"] == "conflict"

    availability = client.get(
        "/availability", params={"item_id": 5, "start": "2025-06-09", "end": "2025-06-12"}
    ).json()
    assert availability["available"] is True
    _book(client, 2, [5, 7], "2025-06-09", "2025-06-12")


def test_cancel_booking_keeps_returned_reservations(
    client: TestClient, clock: FixedClock
) -> None:
    booking = _book(client, 2, [9, 10, 1], "2025-06-09", "2025-06-12")
    camera_id, lens_id, drill_id = booking["reservation_ids"]
    clock.set(clock.today().replace(day=10))
    returned = client.post(f"/reservations/{camera_id}/return", json={"returned_on": "2025-06-10"})
    assert returned.status_code == 200, returned.text

    response = client.post(f"/bookings/{booking['id']}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "returned"
    assert _json(client.get(f"/reservations/{camera_id}"))["status"] == "returned"
    assert _json(client.get(f"/reservations/{lens_id}"))["status"] == "cancelled"
    assert _json(client.get(f"/reservations/{drill_id}"))["status"] == "cancelled"
    assert client.post(f"/bookings/{booking['id']}/cancel").status_code == 409

    invoice = _json(client.get(f"/bookings/{booking['id']}/invoice"))
    assert _lines(invoice) == [("rental", 3, Decimal("45.00"), Decimal("135.00"))]
    assert _totals(invoice) == (
        Decimal("135.00"),
        Decimal("6.75"),
        Decimal("25.65"),
        Decimal("153.90"),
    )


# --- reports -----------------------------------------------------------------------------


def test_revenue_report_uses_booking_discount(client: TestClient) -> None:
    _book(client, 2, [9, 10, 1], "2025-06-09", "2025-06-12", "SPRING10")
    params = {"start": "2025-06-09", "end": "2025-06-10"}
    body = _json(client.get("/reports/revenue", params=params))
    assert body["rows"] == [
        {"category": "photo", "reservations": 2, "revenue": "180.00"},
        {"category": "tools", "reservations": 1, "revenue": "28.80"},
    ]
    assert body["total"] == "208.80"
