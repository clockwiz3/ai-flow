from fastapi.testclient import TestClient


def _invoice(client: TestClient, reservation_id: int) -> dict:
    response = client.get(f"/reservations/{reservation_id}/invoice")
    assert response.status_code == 200, response.text
    return response.json()


def test_invoice_for_regular_customer(client: TestClient) -> None:
    # reservation 4: circular saw (18.00/day), 3 days, regular customer
    body = _invoice(client, 4)
    assert body["lines"] == [
        {
            "kind": "rental",
            "description": "Circular Saw rental (3 days)",
            "quantity": 3,
            "unit_price": "18.00",
            "amount": "54.00",
        }
    ]
    assert (body["subtotal"], body["discount"], body["tax"], body["total"]) == (
        "54.00",
        "0.00",
        "10.80",
        "64.80",
    )


def test_invoice_with_gold_discount(client: TestClient) -> None:
    # reservation 5: family tent (35.00/day), 5 days, gold customer (15%)
    body = _invoice(client, 5)
    assert body["subtotal"] == "175.00"
    assert body["discount"] == "26.25"
    assert body["tax"] == "29.75"
    assert body["total"] == "178.50"


def test_invoice_with_silver_discount(client: TestClient, reserve) -> None:
    created = reserve(1, 2, "2025-06-05", "2025-06-09")
    body = _invoice(client, created["id"])
    assert body["subtotal"] == "48.00"
    assert body["discount"] == "2.40"
    assert body["tax"] == "9.12"
    assert body["total"] == "54.72"


def test_long_rental_gets_free_days(client: TestClient, reserve) -> None:
    created = reserve(7, 1, "2025-06-05", "2025-06-19")
    body = _invoice(client, created["id"])
    line = body["lines"][0]
    assert line["description"] == "Sleeping Bag rental (14 days, 2 free)"
    assert line["quantity"] == 12
    assert line["amount"] == "96.00"
    assert body["total"] == "115.20"


def test_coupon_lowers_total(client: TestClient, reserve) -> None:
    plain = reserve(2, 1, "2025-06-04", "2025-06-07")
    with_coupon = reserve(3, 1, "2025-06-04", "2025-06-07", coupon_code="SPRING10")
    assert _invoice(client, plain["id"])["total"] == "64.80"
    # rotary hammer: 3 x 25.00 = 75.00, 10% off, plus tax
    assert _invoice(client, with_coupon["id"])["total"] == "81.00"


def test_invoice_of_returned_reservation(client: TestClient) -> None:
    body = _invoice(client, 1)
    assert len(body["lines"]) == 1
    assert body["total"] == "43.20"


def test_cancelled_reservation_has_no_invoice(client: TestClient) -> None:
    response = client.get("/reservations/3/invoice")
    assert response.status_code == 409


def test_unknown_reservation_invoice(client: TestClient) -> None:
    assert client.get("/reservations/999/invoice").status_code == 404
