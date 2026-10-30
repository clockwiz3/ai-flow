# Double booking: a longer reservation around an existing one is accepted

**Reported by:** front desk (Lena)
**Severity:** high - we handed the same Family Tent to two customers last weekend

## What happens

When a customer books an item for a period that starts **before** an existing active
reservation and ends **after** it, the system says the item is free and lets the booking
through. The item ends up double-booked.

Shorter bookings that start or end inside an existing reservation are correctly rejected;
it is only the "wraps around it" case that slips through.

## Example (demo data)

Reservation 5 holds the Family Tent (item 6) from 2025-06-10 to 2025-06-15 (status
`active`).

```
GET /availability?item_id=6&start=2025-06-09&end=2025-06-16
```

- **Actual:** `200`, `"available": true`, `"conflicting_reservation_ids": []`
- **Expected:** `"available": false`, with a reason, and `"conflicting_reservation_ids": [5]`

```
POST /reservations
{"item_id": 6, "customer_id": 1, "start": "2025-06-09", "end": "2025-06-16"}
```

- **Actual:** `201 Created` (double booking)
- **Expected:** `409 Conflict`

## Acceptance criteria

- A requested range that fully contains an existing active reservation of the same item is
  reported as unavailable by `GET /availability` (listing that reservation as conflicting)
  and is rejected by `POST /reservations` with 409.
- Overlap rules otherwise stay as documented in the README (half-open ranges: a booking that
  ends on the day another starts, or starts on the day another ends, is still allowed).
