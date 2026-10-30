# Same Family Tent handed to two customers

**Reported by:** front desk (Lena)
**Severity:** high - two families showed up for the same tent

## What happened

Last weekend two customers came to collect the Family Tent (item 6) and we only have one.
Both had a confirmed booking in the system. I've reproduced it with the demo data:

- Reservation 5 (already in the system, status `active`): Family Tent, 2025-06-10 to
  2025-06-15.
- Before booking, I checked the calendar for a customer who wanted the tent from 2025-06-09
  to 2025-06-16:

  ```
  GET /availability?item_id=6&start=2025-06-09&end=2025-06-16
  ```

  It said `"available": true` with no conflicts, so I booked it:

  ```
  POST /reservations
  {"item_id": 6, "customer_id": 1, "start": "2025-06-09", "end": "2025-06-16"}
  ```

  and got `201 Created`.

The tent cannot be with two customers on the same days. The system should have told me it
was taken (listing reservation 5 as the conflict) and refused the booking.

Other bookings for that tent that clash with reservation 5 do get refused, so I don't
understand why this one went through.

## Expected

- The availability check and the booking endpoint never allow an item to be booked for days
  on which it is already held by another active reservation, following the reservation rules
  in the README; the availability answer lists the reservations that are in the way.
- Back-to-back bookings (one ending on the day the next one starts) must keep working - we
  rely on them every weekend.
