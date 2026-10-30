# Multi-item bookings with a bundle discount

## Motivation

Customers rarely rent a single thing: a camping weekend is a tent, sleeping bags and a stove;
a shoot is a camera and two lenses. Today the front desk has to create one reservation per
item, and when the third item turns out to be taken the first two are already booked and
must be cancelled by hand. We want to book several items in **one all-or-nothing request**,
invoice them together, and reward bigger baskets with a **bundle discount**.

## Desired behaviour

### Creating a booking

`POST /bookings` reserves a list of items for one customer and one date range.

- `items` is a list of item ids. It must not be empty and must not contain the same id twice.
- Checks, in this order (the first failing one decides the response):
  1. `items` empty or containing a duplicate -> 422 `invalid_request`
  2. date rules exactly as for `POST /reservations`: `end` after `start`, `start` not in the
     past, at most 90 days -> 422 `invalid_request`
  3. unknown customer -> 404 `not_found`
  4. unknown coupon code -> 422 `invalid_request` (codes are case-insensitive, as for
     reservations)
  5. any unknown item -> 404 `not_found`
  6. availability: an item is unavailable when its status is not `available` or when it has
     an overlapping **active** reservation (README rules; reservations made through other
     bookings count like any other). If **one or more** items are unavailable the request is
     rejected with `409` and the body
     `{"detail": "...", "code": "conflict", "unavailable_item_ids": [...]}` listing **every**
     unavailable item id of the request, in ascending order.
- A rejected request creates **nothing** (no booking, no reservation).
- On success one reservation is created per item, in the order of `items`, so
  `reservation_ids[i]` is the reservation of `items[i]` (ids are ascending). Each reservation
  is an ordinary reservation (same customer, dates and coupon as the booking) that also
  carries the id of its booking.

### Reservations

- Every reservation returned by the API gains `booking_id`: the booking id, or `null` for a
  reservation created through `POST /reservations` (and for the seeded ones).
- All existing reservation endpoints keep working for reservations that belong to a booking:
  a single one can be cancelled, returned and invoiced on its own.

### Booking status

A booking has no stored status; it is derived from its reservations:

- `active` if at least one of its reservations is active;
- otherwise `returned` if at least one is returned;
- otherwise `cancelled`.

### Cancelling a booking

`POST /bookings/{id}/cancel` cancels every **active** reservation of the booking. Returned
(or already cancelled) reservations are left as they are. If the booking has no active
reservation the request fails with `409` (`conflict`) and changes nothing. The response is
the booking with its new derived status.

### Pricing: bundle discount

- A booking that currently has **at least 3 reservations that are not cancelled** gets a
  **bundle discount of 5%**. It is evaluated whenever an invoice is produced, so cancelling
  one reservation of a 3-item booking removes the bundle discount from then on.
- The booking's combined discount rate is `tier + coupon + bundle`, **capped at 30%**
  (the README cap now covers the bundle discount too).
- As always, the discount applies only to rental amounts, never to late fees, and is applied
  before tax.

### Booking invoice

`GET /bookings/{id}/invoice`:

- `lines`: for every reservation of the booking that is not cancelled, in ascending
  reservation id order, its `rental` line followed by its `late_fee` line (if it was
  returned late). Each line is exactly the line the reservation's own invoice shows.
- `subtotal` = sum of all line amounts.
- `discount` = (sum of the amounts of all `rental` lines) x the booking's combined rate,
  rounded **once** to 0.01 (half up). It is not the sum of per-reservation discounts.
- `tax` = 20% of `subtotal - discount`; `total` = `subtotal - discount + tax` (rounded as
  in the README).
- A booking whose reservations are all cancelled has no invoice: `409` (`conflict`).

### Reservation invoice of a booked reservation

`GET /reservations/{id}/invoice` for a reservation that belongs to a booking is computed as
today, except that its discount rate is the booking's combined rate (including the bundle
discount when the booking qualifies at that moment): `discount = its rental amount x
booking rate`. Reservations without a booking are unchanged. The revenue report keeps
counting reservations one by one from their invoices, so booked reservations contribute
with the booking's rate; the report's shape does not change.

## Worked example

Today is 2025-06-02. Silver customer Bob (customer 2, 5%) books the Mirrorless Camera (item
9, 45.00/day), the Telephoto Lens (item 10, 30.00/day) and the Cordless Drill (item 1,
12.00/day) from 2025-06-09 to 2025-06-12 with coupon `SPRING10`:

```
POST /bookings
{"customer_id": 2, "items": [9, 10, 1], "start": "2025-06-09", "end": "2025-06-12", "coupon_code": "SPRING10"}
```

- Rental lines: 3 x 45.00 = 135.00, 3 x 30.00 = 90.00, 3 x 12.00 = 36.00; subtotal 261.00.
- Rate: 5% + 10% + 5% bundle = 20%. Discount 52.20, tax 41.76, total 250.56.
- The camera's own invoice: 135.00, discount 27.00, tax 21.60, total 129.60.
- After cancelling the drill's reservation: 2 reservations left, no bundle, rate 15%;
  booking invoice 225.00, discount 33.75, tax 38.25, total 229.50.
- A gold customer (15%) with `WELCOME20` would get 15 + 20 + 5 = 40%, capped at 30%.

## API contract

### `POST /bookings`

Request (`coupon_code` optional):

```json
{"customer_id": 2, "items": [9, 10, 1], "start": "2025-06-09", "end": "2025-06-12", "coupon_code": "SPRING10"}
```

Response `201`:

```json
{
  "id": 1,
  "customer_id": 2,
  "start": "2025-06-09",
  "end": "2025-06-12",
  "coupon_code": "SPRING10",
  "status": "active",
  "reservation_ids": [7, 8, 9]
}
```

`id` is a positive integer unique across bookings. `coupon_code` is the stored (upper-case)
code or `null`. Errors as described above; a missing or malformed field is FastAPI's usual
422.

### `GET /bookings/{id}`

Response `200`: the booking (same shape, current derived status). `404` (`not_found`) for
an unknown id.

### `POST /bookings/{id}/cancel`

Response `200`: the booking. `404` for an unknown id, `409` when nothing is active.

### `GET /bookings/{id}/invoice`

Response `200`:

```json
{
  "booking_id": 1,
  "customer_id": 2,
  "lines": [{"kind": "rental", "description": "...", "quantity": 3, "unit_price": "45.00", "amount": "135.00"}],
  "subtotal": "261.00",
  "discount": "52.20",
  "tax": "41.76",
  "total": "250.56"
}
```

`404` for an unknown id, `409` when every reservation is cancelled.

## Acceptance criteria

- [ ] Bookings are created all-or-nothing, with the validation order and 409 body above.
- [ ] Reservations expose `booking_id`; per-reservation endpoints keep working.
- [ ] Booking status, cancellation and invoice follow the rules above.
- [ ] Bundle discount, cap, rounding and tax are applied at booking level; booked
      reservations' own invoices and the revenue report use the booking's rate.
- [ ] Existing behaviour and tests are otherwise unaffected.
