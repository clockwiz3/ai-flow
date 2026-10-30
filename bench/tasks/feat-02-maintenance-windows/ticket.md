# Scheduled maintenance windows for items

## Motivation

Today the only way to take an item out of service is to flip its status to `maintenance`,
which blocks it for every date until someone flips it back. The workshop actually plans
servicing in advance ("the camera goes to the service centre 10-12 June"), and in the
meantime customers should still be able to rent the item before and after that period.

We want to schedule **maintenance windows**: date ranges during which a specific item cannot
be rented, while it stays rentable on all other dates.

## Desired behaviour

- A maintenance window belongs to one item and covers a date range `[start, end)`. Like
  reservations, `end` is **exclusive** (the item is back in service on the morning of `end`).
- A window cannot be scheduled over an **active** reservation of the same item (we never
  silently break a customer's booking). Cancelled and returned reservations do not matter.
  Two ranges overlap when they share at least one day (`a.start < b.end and b.start < a.end`).
- Windows of the same item may overlap each other; there is no validation between windows.
- While a window is scheduled, the item is unavailable for any range that overlaps it:
  - `GET /availability` returns `available: false` with
    `reason: "Item is scheduled for maintenance during this period"`.
  - `POST /reservations` for an overlapping range is rejected with `409` (`code: "conflict"`).
  - Ranges that merely touch a window (ending on its `start`, or starting on its `end`) are
    fine.
- Reason precedence in `GET /availability`: the item's own status reason
  (`"Item is under maintenance"` / `"Item is retired"`) comes first, then the maintenance
  window reason above, then the existing "already reserved" reason. Whatever the reason,
  `conflicting_reservation_ids` keeps listing overlapping reservations exactly as today
  (windows are not reservations and never appear in that list).
- Maintenance windows are **not** reservations: the utilization and revenue reports are
  unaffected by them.
- Scheduling a window does not change the item's `status`.

## API contract

### `POST /items/{id}/maintenance`

Request:

```json
{"start": "2025-06-10", "end": "2025-06-12"}
```

Response `201`:

```json
{"id": 1, "item_id": 3, "start": "2025-06-10", "end": "2025-06-12"}
```

`id` is a positive integer, unique across all maintenance windows.

Errors (domain errors use the usual `{"detail": ..., "code": ...}` body):

| Situation | Status | `code` |
| --- | --- | --- |
| Unknown item | 404 | `not_found` |
| `end` not after `start` (empty or inverted range) | 422 | `invalid_request` |
| Missing / malformed dates | 422 | (FastAPI validation error) |
| Overlaps an active reservation of this item | 409 | `conflict` |

### `GET /items/{id}/maintenance`

Response `200`: the item's windows (same shape as above), ordered by `start` ascending, then
by `id`. Empty list if there are none. `404` for an unknown item.

## Acceptance criteria

- [ ] Windows can be scheduled and listed per item.
- [ ] Availability and reservation creation treat an overlapping window as blocking, with the
      reason and precedence described above.
- [ ] Windows overlapping an active reservation are rejected with 409.
- [ ] Reports are unaffected.
- [ ] Existing behaviour and tests are unaffected.
