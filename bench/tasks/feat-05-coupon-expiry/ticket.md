# Coupons with an expiry date

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
