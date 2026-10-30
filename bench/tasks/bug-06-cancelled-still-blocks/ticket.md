# Customer can't book the Telephoto Lens although it is free

**Reported by:** front desk (Lena)
**Severity:** high - we are turning customers away for gear that is sitting on the shelf

## What happens

A customer (Alice, customer 1) wanted the Telephoto Lens (item 10) from 2025-06-05 to
2025-06-08. As far as the shop is concerned those dates should be free - the lens is on the
shelf and nobody is going to collect it - but the system refuses:

```
GET /availability?item_id=10&start=2025-06-05&end=2025-06-08
```

returns `"available": false`, `"reason": "Item is already reserved for part of this period"`,
`"conflicting_reservation_ids": [6]`, and

```
POST /reservations
{"item_id": 10, "customer_id": 1, "start": "2025-06-05", "end": "2025-06-08"}
```

returns `409 Conflict`.

Staff looking at the calendar see the same thing: the lens shows as busy for those days. We
have had a couple of similar "phantom busy" complaints for other items over the last weeks,
so it's probably not specific to this lens.

## Expected

- Availability and booking follow the README rules on which reservations block an item; an
  item that is actually free for the requested dates can be booked (201), and the
  availability check reports it as available with no conflicts.
- Items that really are booked for those days keep being refused, exactly as today.
