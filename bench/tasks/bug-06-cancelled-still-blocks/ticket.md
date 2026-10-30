# Item stays blocked after a reservation is cancelled

**Reported by:** front desk (Lena)
**Severity:** high - we are turning customers away for gear that is actually free

## What happens

After a reservation is cancelled, its dates remain blocked: the availability check reports
the item as already reserved (listing the cancelled reservation as the conflict) and new
bookings for those dates are rejected with 409.

Per the README, only `active` reservations block an item; cancelled and returned
reservations never affect availability.

## Example (demo data)

Reservation 6 for the Telephoto Lens (item 10), 2025-06-05 to 2025-06-08, has status
`cancelled`.

```
GET /availability?item_id=10&start=2025-06-05&end=2025-06-08
```

- **Actual:** `"available": false`, `"reason": "Item is already reserved for part of this period"`,
  `"conflicting_reservation_ids": [6]`
- **Expected:** `"available": true`, `"reason": null`, `"conflicting_reservation_ids": []`

```
POST /reservations
{"item_id": 10, "customer_id": 1, "start": "2025-06-05", "end": "2025-06-08"}
```

- **Actual:** `409 Conflict`
- **Expected:** `201 Created`

The same happens when we cancel a booking ourselves via `POST /reservations/{id}/cancel`:
the slot is not released.

## Acceptance criteria

- Cancelled reservations are ignored by `GET /availability` and by `POST /reservations`.
- Cancelling an active reservation frees its dates immediately.
- Active reservations keep blocking exactly as before; returned reservations keep not
  blocking.
