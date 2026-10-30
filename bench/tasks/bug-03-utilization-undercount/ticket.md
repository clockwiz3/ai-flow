# Utilization report says our gear sits idle when it was out with customers

**Reported by:** operations (Tomasz)
**Severity:** medium - we use this report to decide which items to buy more of and which to
sell off, and since the latest release the numbers look far too low

## What we see

We compared the utilization report with what actually happened at the counter. Two examples
we can reproduce on the demo data:

1. The Two-Person Tent (item 5) went out on 2025-05-10 and the customer brought it back on
   2025-05-16. For the second half of May:

   ```
   GET /reports/utilization?start=2025-05-12&end=2025-06-01
   ```

   the tent's row says `"reserved_days": 0`, `"utilization_pct": "0.0"`. The tent was out
   with the customer for the first few days of that period.

2. The Circular Saw (item 2, reservation 4, booked 2025-06-01 to 2025-06-04) was brought back
   on 2025-06-06 - two days late; the customer was charged a late fee for it. Afterwards
   (with the return registered as `POST /reservations/4/return {"returned_on": "2025-06-06"}`)

   ```
   GET /reports/utilization?start=2025-06-01&end=2025-06-11
   ```

   shows `"reserved_days": 3`, `"utilization_pct": "30.0"` for the saw, although it was not
   in the shop until the 6th.

## Expected

- The utilization report follows the rules in the README ("Reports") for every item and every
  report period.
- Nothing else changes: in particular the revenue report keeps its numbers exactly as they
  are today.
