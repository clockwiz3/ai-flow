# Refactor: one place for pricing and booking rule parameters

**Type:** refactoring (no functional change)
**Area:** `app/services/` (pricing, invoices, reservations, returns)

## Motivation

The numbers that define our commercial rules are scattered over the service modules as
module-level constants: the tax rate and tier discounts in `pricing.py`, the late-fee
multiplier in `returns.py`, the maximum reservation length in `reservations.py`, and so on.
Finance wants to review (and soon tune per shop) all of them in one place, and we want to be
able to run a scenario with different values without editing several files.

## Target structure

Create a new module **`app/settings.py`** containing:

1. A **frozen dataclass** `PricingSettings` (`@dataclass(frozen=True)`) with exactly these
   fields and defaults (the defaults are today's values):

   | Field | Type | Default |
   | --- | --- | --- |
   | `tax_rate` | `Decimal` | `Decimal("0.20")` |
   | `tier_discounts` | mapping `CustomerTier -> Decimal` | regular `Decimal("0")`, silver `Decimal("0.05")`, gold `Decimal("0.15")` |
   | `max_total_discount` | `Decimal` | `Decimal("0.30")` |
   | `free_day_every` | `int` | `7` |
   | `late_fee_multiplier` | `Decimal` | `Decimal("1.5")` |
   | `max_rental_days` | `int` | `90` |

   Rates are fractions (`0.20` means 20%). `PricingSettings()` with no arguments must give
   the defaults above.

2. A module-level default instance: `PRICING = PricingSettings()`.

### How services read the settings (part of the contract)

Services must look the settings up **at call time** through the module attribute
`app.settings.PRICING`, for example:

```python
from app import settings

def free_days(days: int) -> int:
    return days // settings.PRICING.free_day_every
```

Do **not** copy the values at import time (no `from app.settings import PRICING` into a
service, no `TAX_RATE = PRICING.tax_rate` aliases). The supported way to run with other
values is to rebind the module attribute, e.g.

```python
import dataclasses
import app.settings
app.settings.PRICING = dataclasses.replace(app.settings.PRICING, tax_rate=Decimal("0.10"))
```

and every subsequent request (quotes, invoices, returns, reservation validation) must use the
new values.

### Clean-up

- Remove the old module constants `TAX_RATE`, `MAX_TOTAL_DISCOUNT`, `FREE_DAY_EVERY`,
  `TIER_DISCOUNTS` (pricing), `LATE_FEE_MULTIPLIER` (returns) and `MAX_RENTAL_DAYS`
  (reservations). No module in `app/services/` may define them any more or contain the
  literal values (`"0.20"`, `"0.05"`, `"0.15"`, `"0.30"`, `"1.5"`, `7`, `90`) - the
  settings module is the single source of truth.
- Money helpers and other technical constants (`CENT`, `ZERO`, page sizes in `catalog.py`)
  are out of scope and may stay where they are.
- Update the layout table in `README.md` to mention `app/settings.py`.

## Constraints

- **Behaviour must not change.** Every endpoint returns exactly the same status codes,
  bodies and error messages as before for every input. This is a pure refactoring: do not
  fix or change any business logic while you are in there, even if something looks odd.
- All existing tests must keep passing, unmodified, and `ruff check .` must stay clean.

## Acceptance criteria

- `from app.settings import PricingSettings, PRICING` works; `PricingSettings` is a frozen
  dataclass with the fields and defaults listed above; `PRICING` is an instance with the
  defaults.
- Rebinding `app.settings.PRICING` to a modified copy changes the tax on invoices, the tier
  discounts, the free-day rule, the late-fee rate of returns/invoices and the maximum
  reservation length (including the number in the "Reservations are limited to N days"
  error message) without restarting the app.
- None of the old constants or their literal values remain in `app/services/`.
- The API behaves exactly as before; `pytest` and `ruff check .` pass.
