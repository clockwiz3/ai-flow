# Extend an active reservation

## Motivation

Customers regularly call the shop to keep an item a few days longer. Today staff have to
cancel the reservation and book a new one, which loses the original booking and is easy to
get wrong. We want a single "extend" action.

## Desired behaviour

Add an endpoint that moves the `end` date of an existing reservation to a later date. The
`start`, item, customer, coupon and every other field stay the same. Because the invoice is
computed from the reservation's dates, the invoice of an extended reservation automatically
reflects the new length (rental days, free days, discounts and tax as usual).

## API contract

`POST /reservations/{id}/extend`

Request body:

```json
{"end": "2025-06-09"}
```

`end` is the new **exclusive** end date (same convention as everywhere else in Rentwise).

Response `200`: the updated reservation, in the same shape as `GET /reservations/{id}`.

Errors (domain errors use the usual `{"detail": ..., "code": ...}` body):

| Situation | Status | `code` |
| --- | --- | --- |
| Reservation does not exist | 404 | `not_found` |
| Reservation is not `active` (cancelled or returned) | 409 | `conflict` |
| New `end` is not strictly after the current `end` | 422 | `invalid_request` |
| The extended reservation would be longer than 90 days in total (`new end - start > 90`) | 422 | `invalid_request` |
| Another **active** reservation of the same item overlaps the added days `[current end, new end)` | 409 | `conflict` |
| Missing / malformed `end` in the body | 422 | (FastAPI validation error) |

Notes:

- The reservation never conflicts with itself.
- Extending right up to the start of the next booking of the same item is allowed
  (ranges are half-open, so `[a, b)` and `[b, c)` do not overlap).
- A failed extension leaves the reservation unchanged.

## Acceptance criteria

- [ ] `POST /reservations/{id}/extend` extends an active reservation and returns it.
- [ ] `GET /reservations/{id}` and `GET /reservations/{id}/invoice` reflect the new end date.
- [ ] All error cases above return the listed status codes.
- [ ] Existing behaviour and tests are unaffected.
