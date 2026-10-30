"""Behaviour smoke suite: the main API flows must answer exactly as before the refactoring."""

from fastapi.testclient import TestClient


def _ok(response, status: int = 200) -> dict | list:
    assert response.status_code == status, response.text
    return response.json()


def _avail(client: TestClient, item_id: int, start: str, end: str):
    return client.get("/availability", params={"item_id": item_id, "start": start, "end": end})


def _return(client: TestClient, reservation_id: int, returned_on: str):
    return client.post(
        f"/reservations/{reservation_id}/return", json={"returned_on": returned_on}
    )


def test_smoke_health_and_catalog(client: TestClient) -> None:
    assert _ok(client.get("/health")) == {"status": "ok", "today": "2025-06-02"}
    categories = _ok(client.get("/categories"))
    assert [c["id"] for c in categories] == ["camping", "garden", "photo", "tools"]

    page = _ok(client.get("/items"))
    assert page["total"] == 12
    assert [i["id"] for i in page["items"]] == list(range(1, 13))
    assert page["items"][0] == {
        "id": 1,
        "name": "Cordless Drill",
        "category": "tools",
        "daily_rate": "12.00",
        "deposit": "50.00",
        "status": "available",
    }
    camping = _ok(client.get("/items", params={"category": "camping"}))
    assert [i["id"] for i in camping["items"]] == [5, 6, 7, 8]
    tents = _ok(client.get("/items", params={"q": "Tent"}))
    assert [i["id"] for i in tents["items"]] == [5, 6]
    limited = _ok(client.get("/items", params={"limit": 3}))
    assert ([i["id"] for i in limited["items"]], limited["total"]) == ([1, 2, 3], 12)
    assert client.get("/items", params={"limit": 0}).status_code == 422

    assert _ok(client.get("/items/9"))["name"] == "Mirrorless Camera"
    missing = client.get("/items/999")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    created = _ok(
        client.post(
            "/items",
            json={"name": "Pressure Washer", "category": "garden", "daily_rate": "22.00",
                  "deposit": "90.00"},
        ),
        201,
    )
    assert created["id"] == 13
    assert created["status"] == "available"
    bad = client.post(
        "/items", json={"name": "X", "category": "nope", "daily_rate": "1.00", "deposit": "0"}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "invalid_request"

    updated = _ok(client.post("/items/13/status", json={"status": "maintenance"}))
    assert updated["status"] == "maintenance"
    retired = client.post("/items/12/status", json={"status": "available"})
    assert retired.status_code == 409
    assert retired.json()["code"] == "conflict"


def test_smoke_customers_and_coupons(client: TestClient) -> None:
    customers = _ok(client.get("/customers"))
    assert [c["id"] for c in customers] == [1, 2, 3, 4, 5]
    gold = _ok(client.get("/customers", params={"tier": "gold"}))
    assert [c["id"] for c in gold] == [3, 5]
    assert _ok(client.get("/customers/2"))["email"] == "bob@example.com"
    assert client.get("/customers/99").status_code == 404

    created = _ok(
        client.post("/customers", json={"name": "Finn Berg", "email": "Finn@Example.com"}), 201
    )
    assert created == {"id": 6, "name": "Finn Berg", "email": "finn@example.com",
                       "tier": "regular"}
    duplicate = client.post("/customers", json={"name": "F", "email": "FINN@example.com"})
    assert duplicate.status_code == 409

    coupons = _ok(client.get("/coupons"))
    assert coupons == [{"code": "SPRING10", "percent": 10}, {"code": "WELCOME20", "percent": 20}]
    assert _ok(client.post("/coupons", json={"code": "summer5", "percent": 5}), 201) == {
        "code": "SUMMER5",
        "percent": 5,
    }
    assert client.post("/coupons", json={"code": "SUMMER5", "percent": 7}).status_code == 409


def test_smoke_availability(client: TestClient) -> None:
    # reservation 5: item 6, 2025-06-10 .. 2025-06-15 (active)
    inside = _ok(
        _avail(client, 6, "2025-06-12", "2025-06-14")
    )
    assert inside["available"] is False
    assert inside["conflicting_reservation_ids"] == [5]
    assert inside["reason"] == "Item is already reserved for part of this period"

    for start, end in [
        ("2025-06-08", "2025-06-12"),
        ("2025-06-14", "2025-06-20"),
        ("2025-06-10", "2025-06-15"),
    ]:
        body = _ok(_avail(client, 6, start, end))
        assert body["available"] is False, (start, end)
        assert body["conflicting_reservation_ids"] == [5], (start, end)

    for start, end in [("2025-06-15", "2025-06-18"), ("2025-06-05", "2025-06-10")]:
        body = _ok(_avail(client, 6, start, end))
        assert body == {
            "item_id": 6,
            "start": start,
            "end": end,
            "available": True,
            "reason": None,
            "conflicting_reservation_ids": [],
        }

    maintenance = _ok(
        _avail(client, 4, "2025-06-05", "2025-06-07")
    )
    assert maintenance["available"] is False
    assert maintenance["reason"] == "Item is under maintenance"

    inverted = client.get(
        "/availability", params={"item_id": 6, "start": "2025-06-07", "end": "2025-06-07"}
    )
    assert inverted.status_code == 422
    assert inverted.json() == {"detail": "end must be after start", "code": "invalid_request"}
    assert client.get(
        "/availability", params={"item_id": 999, "start": "2025-06-05", "end": "2025-06-07"}
    ).status_code == 404


def test_smoke_reservation_lifecycle(client: TestClient, reserve) -> None:
    created = reserve(7, 2, "2025-06-03", "2025-06-06")
    assert created == {
        "id": 7,
        "item_id": 7,
        "customer_id": 2,
        "start": "2025-06-03",
        "end": "2025-06-06",
        "status": "active",
        "coupon_code": None,
        "created_on": "2025-06-02",
        "returned_on": None,
        "damaged": False,
    }
    # back-to-back bookings are fine (end is exclusive)
    reserve(7, 1, "2025-06-06", "2025-06-08")
    reserve(7, 3, "2025-06-02", "2025-06-03")

    clash = client.post(
        "/reservations",
        json={"item_id": 7, "customer_id": 4, "start": "2025-06-05", "end": "2025-06-07"},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "conflict"

    def post(**overrides) -> int:
        payload = {"item_id": 8, "customer_id": 1, "start": "2025-06-05", "end": "2025-06-07"}
        payload.update(overrides)
        return client.post("/reservations", json=payload).status_code

    assert post(start="2025-06-01") == 422  # in the past
    assert post(end="2025-06-05") == 422  # empty range
    assert post(end="2025-09-03") == 201  # exactly 90 days
    assert post(item_id=5, end="2025-09-04") == 422  # 91 days
    assert post(item_id=5, coupon_code="NOPE") == 422
    assert post(item_id=4) == 409  # maintenance
    assert post(item_id=12) == 409  # retired
    assert post(item_id=999) == 404
    assert post(item_id=5, customer_id=999) == 404
    with_coupon = client.post(
        "/reservations",
        json={"item_id": 1, "customer_id": 1, "start": "2025-06-05", "end": "2025-06-07",
              "coupon_code": "spring10"},
    )
    assert with_coupon.status_code == 201
    assert with_coupon.json()["coupon_code"] == "SPRING10"

    mine = _ok(client.get("/reservations", params={"customer_id": 2}))
    assert [r["id"] for r in mine] == [3, 6, 7]
    for_item = _ok(client.get("/reservations", params={"item_id": 7}))
    assert [r["id"] for r in for_item] == [7, 8, 9]
    cancelled = _ok(client.get("/reservations", params={"status": "cancelled"}))
    assert [r["id"] for r in cancelled] == [3, 6]

    assert _ok(client.post("/reservations/8/cancel"))["status"] == "cancelled"
    assert client.post("/reservations/8/cancel").status_code == 409
    assert _ok(client.get("/reservations/8"))["status"] == "cancelled"
    assert client.get("/reservations/999").status_code == 404
    assert client.post("/reservations/999/cancel").status_code == 404


def test_smoke_returns(client: TestClient) -> None:
    # reservation 4: circular saw (18.00/day, deposit 80.00), 2025-06-01 .. 2025-06-04
    receipt = _ok(_return(client, 4, "2025-06-02"))
    assert receipt == {
        "reservation_id": 4,
        "returned_on": "2025-06-02",
        "late_days": 0,
        "late_fee": "0.00",
        "damaged": False,
        "deposit": "80.00",
        "deposit_refunded": "80.00",
        "deposit_withheld": "0.00",
    }
    assert _ok(client.get("/reservations/4"))["status"] == "returned"
    assert client.post("/reservations/4/return").status_code == 409
    assert _ok(client.get("/items/2"))["status"] == "available"
    assert client.post("/reservations/3/return").status_code == 409


def test_smoke_damaged_return(client: TestClient) -> None:
    receipt = _ok(client.post("/reservations/4/return", json={"damaged": True}))
    assert receipt["returned_on"] == "2025-06-02"
    assert receipt["deposit_refunded"] == "0.00"
    assert receipt["deposit_withheld"] == "80.00"
    assert _ok(client.get("/items/2"))["status"] == "maintenance"


def test_smoke_return_date_rules(client: TestClient) -> None:
    assert _return(client, 4, "2025-05-31").status_code == 422
    assert _return(client, 4, "2025-06-03").status_code == 422


def test_smoke_invoices(client: TestClient, reserve) -> None:
    regular = _ok(client.get("/reservations/4/invoice"))
    assert regular == {
        "reservation_id": 4,
        "customer_id": 4,
        "lines": [
            {
                "kind": "rental",
                "description": "Circular Saw rental (3 days)",
                "quantity": 3,
                "unit_price": "18.00",
                "amount": "54.00",
            }
        ],
        "subtotal": "54.00",
        "discount": "0.00",
        "tax": "10.80",
        "total": "64.80",
    }
    gold = _ok(client.get("/reservations/5/invoice"))
    assert (gold["subtotal"], gold["discount"], gold["tax"], gold["total"]) == (
        "175.00", "26.25", "29.75", "178.50",
    )
    returned = _ok(client.get("/reservations/2/invoice"))
    assert returned["lines"][0]["description"] == "Two-Person Tent rental (7 days, 1 free)"
    assert (returned["subtotal"], returned["discount"], returned["tax"], returned["total"]) == (
        "120.00", "18.00", "20.40", "122.40",
    )

    silver = reserve(8, 2, "2025-06-03", "2025-06-24")  # camping stove 6.50, 21 days
    body = _ok(client.get(f"/reservations/{silver['id']}/invoice"))
    assert body["lines"][0]["quantity"] == 18
    assert (body["subtotal"], body["discount"], body["tax"], body["total"]) == (
        "117.00", "5.85", "22.23", "133.38",
    )
    odd = reserve(10, 5, "2025-06-09", "2025-06-12")  # telephoto 30.00, 3 days, gold
    body = _ok(client.get(f"/reservations/{odd['id']}/invoice"))
    assert (body["subtotal"], body["discount"], body["tax"], body["total"]) == (
        "90.00", "13.50", "15.30", "91.80",
    )

    assert client.get("/reservations/3/invoice").status_code == 409
    assert client.get("/reservations/999/invoice").status_code == 404


def test_smoke_reports(client: TestClient) -> None:
    revenue = _ok(
        client.get("/reports/revenue", params={"start": "2025-05-01", "end": "2025-05-15"})
    )
    assert revenue == {
        "start": "2025-05-01",
        "end": "2025-05-15",
        "rows": [
            {"category": "camping", "reservations": 1, "revenue": "102.00"},
            {"category": "tools", "reservations": 1, "revenue": "36.00"},
        ],
        "total": "138.00",
    }
    empty = _ok(client.get("/reports/revenue", params={"start": "2024-01-01", "end": "2024-02-01"}))
    assert (empty["rows"], empty["total"]) == ([], "0.00")
    assert client.get(
        "/reports/revenue", params={"start": "2025-05-15", "end": "2025-05-01"}
    ).status_code == 422

    util = _ok(
        client.get("/reports/utilization", params={"start": "2025-06-01", "end": "2025-06-11"})
    )
    rows = {row["item_id"]: row for row in util["rows"]}
    assert 12 not in rows
    assert sorted(rows) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert rows[2] == {
        "item_id": 2,
        "item_name": "Circular Saw",
        "reserved_days": 3,
        "period_days": 10,
        "utilization_pct": "30.0",
    }
    assert (rows[6]["reserved_days"], rows[6]["utilization_pct"]) == (1, "10.0")
    assert (rows[1]["reserved_days"], rows[1]["utilization_pct"]) == (0, "0.0")

    thirds = _ok(
        client.get("/reports/utilization", params={"start": "2025-06-01", "end": "2025-06-04"})
    )
    assert {r["item_id"]: r["utilization_pct"] for r in thirds["rows"]}[2] == "100.0"
    odd = _ok(
        client.get("/reports/utilization", params={"start": "2025-06-12", "end": "2025-06-18"})
    )
    assert {r["item_id"]: r["utilization_pct"] for r in odd["rows"]}[6] == "50.0"
    nine = _ok(
        client.get("/reports/utilization", params={"start": "2025-06-07", "end": "2025-06-16"})
    )
    row6 = {r["item_id"]: r for r in nine["rows"]}[6]
    assert (row6["reserved_days"], row6["period_days"], row6["utilization_pct"]) == (5, 9, "55.6")
