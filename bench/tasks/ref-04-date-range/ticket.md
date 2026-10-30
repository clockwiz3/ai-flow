# Refactor: a `DateRange` value object for `[start, end)` ranges

**Type:** refactoring
**Area:** `app/` (new module), `app/models.py`, `app/services/` (availability, reservations,
reports)

## Motivation

Every service re-implements half-open date range logic with raw `start`/`end` pairs:
`availability.py` has its own overlap check, `reservations.py` computes the rental length by
hand, `reports.py` does `min`/`max` date arithmetic for utilization and its own
"start falls in the period" test. Hand-written date comparisons like these are easy to get
subtly wrong and hard to review. We want one small, well-tested value object that encodes the
README rule ("all date ranges are half-open `[start, end)`") once.

## Target structure

### `app/daterange.py`

A **frozen dataclass** `DateRange` with fields `start: date` and `end: date` (`end` is
exclusive), constructed as `DateRange(start, end)` or `DateRange(start=..., end=...)`:

- Construction validates the range: unless `start < end`, it raises **`ValueError`**
  (empty and inverted ranges are invalid).
- `days` (property) -> `int`: number of days in the range, `(end - start).days`.
- `contains(day: date) -> bool`: `start <= day < end`.
- `overlaps(other: DateRange) -> bool`: `True` exactly when the two ranges share at least
  one day. It is symmetric; ranges that only touch (one ends on the day the other starts) do
  **not** overlap; a range that contains, is contained in, or equals the other **does**
  overlap.
- `overlap_days(other: DateRange) -> int`: number of days both ranges share, `0` when they
  do not overlap.

Being a frozen dataclass, instances are immutable, comparable with `==` and hashable.

### `app/models.py`

`Reservation` gets a read-only property `period -> DateRange` (`DateRange(self.start,
self.end)`). The existing `Reservation.days` property keeps working.

### Services

- `app.services.availability.validate_range(start, end)` keeps raising
  `InvalidRequestError("end must be after start")` for invalid ranges, but now **returns the
  `DateRange`** for valid ones.
- `availability.py`: the conflict check uses `DateRange.overlaps` (e.g.
  `reservation.period.overlaps(requested)`); the hand-written overlap helper goes away.
- `reservations.py`: the maximum-length rule uses `DateRange.days`.
- `reports.py`: the revenue report uses `DateRange.contains` for "the reservation starts in
  the period"; the utilization report uses `DateRange.days` for the period length and
  `overlap_days` for the reserved days.
- No hand-written `end - start` style date arithmetic or start/end comparisons for ranges
  remain in `availability.py`, `reservations.py` or `reports.py`. (Return/late-fee logic in
  `returns.py` is out of scope - leave it alone.)
- Add `app/daterange.py` to the layout table in `README.md`.

## Constraints

- **The API behaviour must not change**, except where the current code disagrees with the
  `DateRange` semantics above (and with the README rules they encode). Wherever a service
  starts using `DateRange`, its observable behaviour must be exactly what `DateRange` defines -
  do not reproduce quirks of the old hand-written logic. Everything else - which reservation
  statuses block an item, error status codes and messages (`"end must be after start"`,
  `"Reservations are limited to 90 days"`, ...), invoice figures, report numbers - must stay
  exactly as it is today. Do not fix or change any other business logic, even if something
  looks odd.
- All existing tests must keep passing, unmodified, and `ruff check .` must stay clean.

## Acceptance criteria

- `from app.daterange import DateRange` works and `DateRange` behaves as specified
  (validation with `ValueError`, `days`, half-open `contains`, symmetric `overlaps` with
  touching ranges not overlapping, `overlap_days`).
- `Reservation.period` returns the reservation's `DateRange`.
- `validate_range` returns a `DateRange` and still raises `InvalidRequestError` for empty or
  inverted ranges.
- Availability, reservations and reports use `DateRange` instead of ad-hoc date arithmetic.
- The API behaves as before, except where the old logic disagreed with `DateRange` semantics.
- `pytest` and `ruff check .` pass.
