# Customer complaint: charged a late fee for a saw returned on time

**Reported by:** customer support (forwarded e-mail)
**Severity:** medium - the customer wants a refund and says she will not rent from us again

## Customer's message (summarised)

> I rented a Circular Saw from you from 1 June to 4 June 2025. When I booked, I was told to
> bring it back on the 4th, and I did - I dropped it off at the counter on the morning of
> 4 June. My invoice now has an extra "late fee" of 27.00 on it and the total is 97.20
> instead of the 64.80 I expected. Why am I paying for being late when I returned it on the
> agreed date?

## What we found in the system (demo data)

This is reservation 4 (item 2, Circular Saw, 18.00/day, regular customer, 2025-06-01 to
2025-06-04). The return was registered with:

```
POST /reservations/4/return
{"returned_on": "2025-06-04"}
```

The return receipt shows `"late_days": 1` and `"late_fee": "27.00"`, and
`GET /reservations/4/invoice` has a `late_fee` line next to the rental line, total `97.20`.

## Expected

Returns, late fees and invoices follow the rules in the README. This customer should not have
been charged anything beyond the rental.
