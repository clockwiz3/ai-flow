# Coupons with an expiry date

## Ticket

## Motivation

Marketing runs seasonal campaigns ("SUMMER15 valid until end of August"), but coupons in
Rentwise live forever, so someone has to remember to stop honouring them. We want coupons to
optionally carry an expiry date that the system enforces at booking time.

## Desired behaviour

- A coupon may have an optional `expires_on` date. Without it the coupon never expires
  (existing coupons, including the seeded `SPRING10` and `WELCOME20`, keep working as today).
- `expires_on` is the **last day the coupon can be used, inclusive**: a coupon with
  `expires_on = 2025-06-02` is still accepted on 2025-06-02 and rejected from 2025-06-03 on.
- "Today" is the service's injectable clock (the same "today" used for the "reservations
  cannot start in the past" rule), **not** the reservation's `start` date. Booking on
  2025-06-02 a rental that starts on 2025-07-01 with a coupon expiring on 2025-06-30 is fine.
- The check happens only when a reservation is created. Reservations that were booked with a
  coupon that has since expired keep their discount (their invoice is computed exactly as
  before).
- Creating a coupon whose `expires_on` is already in the past is allowed (no validation on
  the date itself beyond it being a valid date).

## API contract

### `POST /coupons`

Request accepts an optional `expires_on` (ISO date, or `null` / omitted for "never"):

```json
{"code": "SUMMER15", "percent": 15, "expires_on": "2025-08-31"}
```

The response (`201`) and every entry of `GET /coupons` include `expires_on`, as an ISO date
string or `null`:

```json
{"code": "SUMMER15", "percent": 15, "expires_on": "2025-08-31"}
```

A malformed `expires_on` is rejected with FastAPI's default `422`.

### `POST /reservations`

Using an expired coupon is rejected with `422`,
`{"detail": "...", "code": "invalid_request"}`, where `detail` says that the coupon has
expired (the message must contain the word "expired"). No reservation is created.

Unknown coupon codes are still rejected with `422` as today.

## Acceptance criteria

- [ ] Coupons can be created with or without `expires_on`, and it is returned by the API.
- [ ] Expired coupons are rejected on `POST /reservations` with 422 and a message mentioning
      the expiry; a coupon is still valid on its `expires_on` day.
- [ ] Existing reservations and coupons without an expiry date are unaffected.

## Plan

Add an optional `expires_on` date to coupons. It is stored on the coupon, returned by POST/GET /coupons, and checked against the injected clock's "today" (inclusive last day) when POST /reservations is called with a coupon code. Invoices, returns and existing reservations are untouched because the check lives only in reservation creation. Model field goes on CouponCreate so it flows through storage (model_dump) and the API schema with no extra plumbing; the seeded coupons keep the default None.

## Files
- modify `app/models.py`: Add `expires_on: date | None = None` to CouponCreate (inherited by Coupon, so it appears in responses and list output). Validation of the ISO date is pydantic's default, giving 422 on malformed values.
- modify `app/services/reservations.py`: In create_reservation, after the coupon lookup succeeds, reject with InvalidRequestError (422) if coupon.expires_on is not None and today > coupon.expires_on, with a message containing 'expired'. Use the clock's `today` already computed (not data.start). Must run before ensure_available so no reservation is created.
- modify `tests/test_pricing.py`: Update test_list_coupons expectations to include `expires_on: None` for seeded coupons; add tests for creating a coupon with a date, creating without it, and a malformed date returning 422.
- modify `tests/test_reservations.py`: Add tests: coupon accepted on its expires_on day, rejected the day after with 422 and 'expired' in detail, no reservation created on rejection, expiry judged by booking day not start date (future start still rejected/accepted per clock), coupon without expiry unaffected.
- modify `README.md`: Spec update: document optional `expires_on` (inclusive last usable day, checked against today at reservation creation, not start; no effect on existing reservations) under Pricing/Reservations and the coupon API notes.

## Checkpoints
1. **Coupon model accepts and returns expires_on**
   - Add `expires_on: date | None = None` to CouponCreate in app/models.py (date is already imported).
   - Update tests/test_pricing.py: test_list_coupons expects `expires_on: None` on SPRING10 and WELCOME20; test_create_coupon expects `expires_on` echoed back as null when omitted.
   - Add tests: POST with expires_on '2025-08-31' returns 201 with that string and GET /coupons lists it; POST with expires_on 'not-a-date' returns 422; POST with explicit null returns null.
   - done when: pytest tests/test_pricing.py passes; create/list responses include expires_on as ISO string or null; malformed date gives 422.
2. **Reject expired coupons at reservation creation**
   - In app/services/reservations.py create_reservation, after the coupon lookup, if coupon.expires_on is not None and today > coupon.expires_on, raise InvalidRequestError with a message such as 'Coupon X has expired'. Keep it before ensure_available.
   - Add tests in tests/test_reservations.py using the clock fixture (SEED_TODAY 2025-06-02): create a coupon expiring 2025-06-02 via POST /coupons and book on 2025-06-02 -> 201; set the clock to 2025-06-03 (clock.set) and book again -> 422 with 'expired' in detail and code 'invalid_request'; confirm GET /reservations count unchanged.
   - Add tests: a rental starting 2025-07-01 booked on 2025-06-02 with a coupon expiring 2025-06-30 is accepted; a coupon with expires_on in the past can still be created but is rejected on booking; unknown coupon still 422; coupon without expiry still works on a far-future booking.
   - done when: Full pytest run passes; expired coupon yields 422 with 'expired' and no reservation is stored; expiry boundary (inclusive) and start-date independence are covered by tests.
3. **Document the rule in the spec**
   - In README.md Pricing section, add that coupons may carry an optional `expires_on` (inclusive last day of use, judged against today when the reservation is created, not the rental start; no expiry if omitted).
   - In README.md Reservations rules, add that an expired coupon is rejected with 422 and that existing reservations keep their discount.
   - Run `ruff check .` and `pytest -q`.
   - done when: README describes the behaviour; ruff and pytest are clean.

## Acceptance criteria
- POST /coupons accepts optional expires_on (ISO date or null/omitted); 201 response and every GET /coupons entry include expires_on as ISO string or null.
- A malformed expires_on returns FastAPI's default 422.
- POST /reservations with a coupon whose expires_on is before the clock's today returns 422 with code 'invalid_request' and a detail containing 'expired', and creates no reservation.
- A coupon is accepted on its expires_on day and rejected from the following day.
- Expiry is judged against the clock's today, not the reservation start date.
- Coupons without expires_on (including seeded SPRING10 and WELCOME20) behave exactly as before; unknown coupon codes still return 422.
- Existing reservations and invoices are unchanged (invoice computation does not check expiry).
- Creating a coupon with an already-past expires_on succeeds (201).

## Risks
- Existing test_list_coupons asserts exact dicts; it will fail until updated to include expires_on: null. Expected, not a regression.
- Check ordering: the expiry check must happen before ensure_available and must not create or allocate a reservation id (allocate_id is called only at construction, after the checks, so keep it that way).
- Invoices (app/services/invoices.py) call lookup_coupon for any reservation with a coupon code; they must not gain an expiry check, otherwise existing reservations would change. Do not add the check to lookup_coupon, which is shared by invoices and pricing.
- Timezone/clock: the check relies on the injected clock; SystemClock uses date.today(), so boundary behaviour near midnight depends on host time. Tests should use FixedClock.
- Boundary off-by-one: the rule is 'rejected when today > expires_on'; a test pinned exactly on expires_on and on expires_on+1 is needed.
- Coupon codes are normalised to upper case and looked up case-insensitively; the expiry check uses the stored coupon object, so this is unaffected.
- The spec says MAX_RENTAL_DAYS/start-in-past rules run before coupon validation; the expiry error will therefore only appear for otherwise-valid requests. This ordering is consistent with the current code.
- Not in scope, noticed only: CouponCreate has no validation that expires_on is not too far in the future or that it is after creation; the ticket explicitly allows past dates. No existing spec deviations were found in the code paths touched.

## Gates

| gate | result | details |
| --- | --- | --- |
| plan | pass | 5 files, 3 checkpoints |
| test | pass | all checks pass |
| review | pass | approve |

## Cost

| agent | status | steps | $ |
| --- | --- | ---: | ---: |
| planner | done | 5 | 0.0061 |
| implementer.cp1 | done | 8 | 0.0037 |
| implementer.cp2 | done | 6 | 0.0036 |
| implementer.cp3 | done | 4 | 0.0016 |
| reviewer | done | 8 | 0.0012 |
| **total** | | | **0.0163** |

<details><summary>Diff</summary>

```diff
diff --git a/README.md b/README.md
index 1b28a59..8ae601c 100644
--- a/README.md
+++ b/README.md
@@ -72,6 +72,9 @@ A reservation has `item_id`, `customer_id`, `start`, `end`, optional `coupon_cod
 - `end` must be after `start`; a reservation may last at most 90 days.
 - `start` may not be in the past (today is allowed).
 - The item and customer must exist; an unknown coupon code is rejected (422).
+- A coupon past its `expires_on` (see Pricing) is rejected with 422 and no reservation is
+  created. Existing reservations keep their discount: expiry is only checked at creation and
+  invoices are computed as before.
 - The item must be `available`.
 - **An item cannot have overlapping active reservations.** Two ranges overlap when they
   share at least one day, i.e. `a.start < b.end and b.start < a.end`. This includes a new
@@ -90,6 +93,11 @@ accepted, with a reason and the ids of the conflicting reservations.
 - Rental amount = `daily_rate * billable_days`.
 - Tier discount: regular 0%, silver 5%, gold 15%.
 - Coupons (`POST /coupons`): an upper-case alphanumeric code with a percent off (1..100).
+- A coupon may carry an optional `expires_on` date. It is the **last day the coupon can be
+  used, inclusive**: with `expires_on = 2025-06-02` the coupon is accepted on 2025-06-02 and
+  rejected from 2025-06-03. "Today" is the service clock, checked when the reservation is
+  created, **not** the rental `start`. Without `expires_on` the coupon never expires.
+  Creating a coupon with a past `expires_on` is allowed.
 - Tier and coupon discounts **add up** (silver 5% + 10% coupon = 15%) and the combined
   discount is **capped at 30%** (gold 15% + 20% coupon = 30%, not 35%).
 - Discounts apply **only to the rental amount** and are applied **before tax**.
@@ -147,8 +155,8 @@ tax 29.75, total 178.50.
 | GET | `/customers` | `tier` filter |
 | POST | `/customers` | 201, 409 on duplicate e-mail |
 | GET | `/customers/{id}` | |
-| GET | `/coupons` | |
-| POST | `/coupons` | 201, 409 on duplicate code |
+| GET | `/coupons` | includes `expires_on` (ISO date or null) |
+| POST | `/coupons` | 201, 409 on duplicate code; optional `expires_on` |
 | GET | `/availability` | `item_id`, `start`, `end` |
 | GET | `/reservations` | `customer_id`, `item_id`, `status` filters |
 | POST | `/reservations` | 201 |
diff --git a/app/models.py b/app/models.py
index 9c82ce8..8d96663 100644
--- a/app/models.py
+++ b/app/models.py
@@ -108,6 +108,9 @@ class Customer(CustomerCreate):
 class CouponCreate(DomainModel):
     code: str = Field(min_length=3, max_length=20)
     percent: int = Field(ge=1, le=100, description="Percent off the rental subtotal.")
+    expires_on: date | None = Field(
+        default=None, description="Last day the coupon can be used (inclusive); None = never."
+    )
 
     @field_validator("code")
     @classmethod
diff --git a/app/services/reservations.py b/app/services/reservations.py
index 88982f8..6e20847 100644
--- a/app/services/reservations.py
+++ b/app/services/reservations.py
@@ -60,6 +60,8 @@ def create_reservation(store: Store, clock: Clock, data: ReservationCreate) -> R
         coupon = lookup_coupon(store, data.coupon_code)
         if coupon is None:
             raise InvalidRequestError(f"Unknown coupon code {data.coupon_code!r}")
+        if coupon.expires_on is not None and today > coupon.expires_on:
+            raise InvalidRequestError(f"Coupon {coupon.code} has expired")
         coupon_code = coupon.code
 
     ensure_available(store, item, data.start, data.end)
diff --git a/tests/test_pricing.py b/tests/test_pricing.py
index 1a2f8f0..fecfe74 100644
--- a/tests/test_pricing.py
+++ b/tests/test_pricing.py
@@ -50,18 +50,43 @@ def test_coupon_for_regular_customer() -> None:
 
 def test_list_coupons(client: TestClient) -> None:
     assert client.get("/coupons").json() == [
-        {"code": "SPRING10", "percent": 10},
-        {"code": "WELCOME20", "percent": 20},
+        {"code": "SPRING10", "percent": 10, "expires_on": None},
+        {"code": "WELCOME20", "percent": 20, "expires_on": None},
     ]
 
 
 def test_create_coupon(client: TestClient) -> None:
     response = client.post("/coupons", json={"code": "summer5", "percent": 5})
     assert response.status_code == 201
-    assert response.json() == {"code": "SUMMER5", "percent": 5}
+    assert response.json() == {"code": "SUMMER5", "percent": 5, "expires_on": None}
     assert "SUMMER5" in [c["code"] for c in client.get("/coupons").json()]
 
 
+def test_create_coupon_with_expiry(client: TestClient) -> None:
+    response = client.post(
+        "/coupons", json={"code": "summer15", "percent": 15, "expires_on": "2025-08-31"}
+    )
+    assert response.status_code == 201
+    assert response.json() == {"code": "SUMMER15", "percent": 15, "expires_on": "2025-08-31"}
+    listed = {c["code"]: c for c in client.get("/coupons").json()}
+    assert listed["SUMMER15"]["expires_on"] == "2025-08-31"
+
+
+def test_create_coupon_with_explicit_null_expiry(client: TestClient) -> None:
+    response = client.post(
+        "/coupons", json={"code": "forever", "percent": 5, "expires_on": None}
+    )
+    assert response.status_code == 201
+    assert response.json()["expires_on"] is None
+
+
+def test_create_coupon_with_malformed_expiry_rejected(client: TestClient) -> None:
+    response = client.post(
+        "/coupons", json={"code": "BADDATE", "percent": 5, "expires_on": "not-a-date"}
+    )
+    assert response.status_code == 422
+
+
 def test_duplicate_coupon_rejected(client: TestClient) -> None:
     response = client.post("/coupons", json={"code": "spring10", "percent": 15})
     assert response.status_code == 409
diff --git a/tests/test_reservations.py b/tests/test_reservations.py
index 0d54924..14842d6 100644
--- a/tests/test_reservations.py
+++ b/tests/test_reservations.py
@@ -1,3 +1,5 @@
+from datetime import date
+
 from fastapi.testclient import TestClient
 
 
@@ -100,3 +102,63 @@ def test_list_reservations_filters(client: TestClient) -> None:
 def test_unknown_reservation(client: TestClient) -> None:
     assert client.get("/reservations/404").status_code == 404
     assert client.post("/reservations/404/cancel").status_code == 404
+
+
+def _create_coupon(client: TestClient, code: str, expires_on: str | None) -> None:
+    response = client.post(
+        "/coupons", json={"code": code, "percent": 15, "expires_on": expires_on}
+    )
+    assert response.status_code == 201, response.text
+
+
+def test_coupon_accepted_on_its_expiry_day(client: TestClient, clock, reserve) -> None:
+    _create_coupon(client, "LASTDAY", "2025-06-02")
+    body = reserve(1, 1, "2025-06-05", "2025-06-08", coupon_code="LASTDAY")
+    assert body["coupon_code"] == "LASTDAY"
+
+
+def test_coupon_rejected_the_day_after_expiry(client: TestClient, clock, reserve) -> None:
+    _create_coupon(client, "LASTDAY", "2025-06-02")
+    clock.set(date(2025, 6, 3))
+    payload = _payload(1, 1, "2025-06-05", "2025-06-08", coupon_code="LASTDAY")
+    response = client.post("/reservations", json=payload)
+    assert response.status_code == 422
+    assert response.json()["code"] == "invalid_request"
+    assert "expired" in response.json()["detail"]
+
+
+def test_expired_coupon_stores_no_reservation(client: TestClient, clock) -> None:
+    _create_coupon(client, "LASTDAY", "2025-06-02")
+    before = len(client.get("/reservations").json())
+    clock.set(date(2025, 6, 3))
+    payload = _payload(1, 1, "2025-06-05", "2025-06-08", coupon_code="LASTDAY")
+    assert client.post("/reservations", json=payload).status_code == 422
+    assert len(client.get("/reservations").json()) == before
+
+
+def test_expiry_judged_by_booking_day_not_start(client: TestClient, reserve) -> None:
+    # Booked on 2025-06-02 (today), rental starts 2025-07-01, coupon valid through 2025-06-30.
+    _create_coupon(client, "JUNE30", "2025-06-30")
+    body = reserve(1, 1, "2025-07-01", "2025-07-04", coupon_code="JUNE30")
+    assert body["coupon_code"] == "JUNE30"
+
+
+def test_coupon_with_past_expiry_created_but_rejected_on_booking(client: TestClient) -> None:
+    _create_coupon(client, "OLDONE", "2025-01-01")
+    payload = _payload(1, 1, "2025-06-05", "2025-06-08", coupon_code="OLDONE")
+    response = client.post("/reservations", json=payload)
+    assert response.status_code == 422
+    assert "expired" in response.json()["detail"]
+
+
+def test_unknown_coupon_still_rejected_with_expiry_logic(client: TestClient) -> None:
+    payload = _payload(1, 1, "2025-06-05", "2025-06-08", coupon_code="GHOST")
+    response = client.post("/reservations", json=payload)
+    assert response.status_code == 422
+    assert "expired" not in response.json()["detail"]
+
+
+def test_coupon_without_expiry_works_on_far_future_booking(client: TestClient, reserve) -> None:
+    _create_coupon(client, "FOREVER", None)
+    body = reserve(1, 1, "2025-08-01", "2025-08-04", coupon_code="FOREVER")
+    assert body["coupon_code"] == "FOREVER"

```

</details>
