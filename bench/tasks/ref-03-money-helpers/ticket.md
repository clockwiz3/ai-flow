# Refactor: one module for money rounding

**Type:** refactoring (no functional change)
**Area:** `app/services/` (pricing, invoices, returns, reports)

## Motivation

Rounding is done in several places: `money()` lives in `app/services/pricing.py` and is
imported by unrelated services, invoices repeat the `money(amount * rate)` pattern for every
discount and tax figure, and the utilization report calls `Decimal.quantize(...,
ROUND_HALF_UP)` by hand. We want a single, small, well-tested module that owns every
rounding rule, so nobody re-implements it (and gets the rounding mode wrong) again.

## Target structure

Create **`app/money.py`** with:

- `CENT = Decimal("0.01")` and `ZERO = Decimal("0")` (moved here from `pricing.py`).
- `to_money(value) -> Decimal` - converts `value` (a `Decimal`, `int` or numeric `str`) to
  `Decimal` and rounds it to cents with `ROUND_HALF_UP`.
  `to_money(Decimal("2.675")) == Decimal("2.68")`, `to_money(Decimal("-1.005")) ==
  Decimal("-1.01")`, `to_money(7) == Decimal("7.00")`. The result always has exactly two
  decimal places.
- `apply_percent(amount: Decimal, rate: Decimal) -> Decimal` - returns
  `to_money(amount * rate)`, where `rate` is a **fraction** (`Decimal("0.15")` means 15%).
  Neither `amount` nor `rate` is rounded before multiplying: there is exactly one rounding
  step, at the end. `apply_percent(Decimal("175.00"), Decimal("0.15")) == Decimal("26.25")`.
- `to_percent(part, whole) -> Decimal` - `part * 100 / whole` rounded to **one** decimal
  place with `ROUND_HALF_UP` (`to_percent(5, 9) == Decimal("55.6")`,
  `to_percent(1, 16) == Decimal("6.3")`, `to_percent(3, 3) == Decimal("100.0")`). Accepts
  `int` or `Decimal` arguments; `whole` is never zero.

Then use these helpers everywhere:

- Every place that rounds money calls `to_money`; every "amount times rate, rounded"
  (the discount and tax figures in `invoices.py`) calls `apply_percent`; the utilization
  percentage in `reports.py` calls `to_percent`.
- Services import `ZERO` (and anything else they need) from `app.money`.
- After the change, **no module under `app/` other than `app/money.py` may call
  `.quantize(` or pass a `rounding=` mode.**
- `app.services.pricing.money` is imported by existing tests, so it must stay importable,
  but only as a thin alias of `to_money` (e.g. `money = to_money`); no service may keep
  using it.
- Add `app/money.py` to the layout table in `README.md`.

## Constraints

- **Behaviour must not change.** Every endpoint returns exactly the same figures, status
  codes and bodies as before, for every input. This is a pure refactoring: do not change
  the order of operations of any calculation or "fix" anything you think looks wrong in the
  pricing or invoice logic.
- All existing tests must keep passing, unmodified, and `ruff check .` must stay clean.

## Acceptance criteria

- `from app.money import to_money, apply_percent, to_percent, ZERO, CENT` works and the
  functions behave exactly as specified above (half-up, single rounding step, `Decimal`
  results).
- `invoices.py`, `pricing.py`, `returns.py` and `reports.py` use `app.money`; no
  `.quantize(` / `rounding=` remains outside `app/money.py`.
- Invoices, returns and reports produce exactly the same numbers as before.
- `pytest` and `ruff check .` pass.
