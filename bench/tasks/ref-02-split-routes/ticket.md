# Refactor: one router module per resource

**Type:** refactoring (no functional change)
**Area:** `app/api/`, `app/main.py`

## Motivation

`app/api/routes.py` holds every HTTP route of the service in a single 200+ line file. Every
feature branch touches it and we keep getting merge conflicts. Split it so that each
resource has its own module.

## Target structure

Replace `app/api/routes.py` with these modules. Each one exposes a module-level
`router: fastapi.APIRouter` holding exactly the routes listed for it:

| Module | Routes |
| --- | --- |
| `app/api/health.py` | `GET /health` |
| `app/api/catalog.py` | `GET /categories`, `GET /items`, `POST /items`, `GET /items/{item_id}`, `POST /items/{item_id}/status` |
| `app/api/customers.py` | `GET /customers`, `POST /customers`, `GET /customers/{customer_id}` |
| `app/api/coupons.py` | `GET /coupons`, `POST /coupons` |
| `app/api/availability.py` | `GET /availability` |
| `app/api/reservations.py` | `GET /reservations`, `POST /reservations`, `GET /reservations/{reservation_id}`, `POST /reservations/{reservation_id}/cancel`, `POST /reservations/{reservation_id}/return`, `GET /reservations/{reservation_id}/invoice` |
| `app/api/reports.py` | `GET /reports/revenue`, `GET /reports/utilization` |

- The route handlers themselves move into those modules unchanged: same function names,
  same paths, methods, `tags`, `response_model`s, `status_code`s, parameters and bodies
  (the generated OpenAPI operations, e.g. their `operationId`s, must stay the same).
- The shared dependencies (`get_store`, `get_clock`, `StoreDep`, `ClockDep`) move to a
  small shared module, `app/api/deps.py`, imported by the resource modules.
- `app/main.py:create_app` includes all seven routers (directly, or through an aggregate
  router defined in `app/api/__init__.py` - your choice). The handlers that serve requests
  must be the ones defined in the resource modules above.
- **Delete `app/api/routes.py`**; nothing may import it any more (no compatibility shim).
- Update the layout table in `README.md`.

## Constraints

- **Behaviour must not change.** Every endpoint keeps exactly the same status codes,
  response bodies and error messages, and the application exposes exactly the same set of
  (method, path) routes as before - no route added, removed or renamed. This is a pure
  move: do not fix or change any business logic, even if something looks odd.
- All existing tests must keep passing, unmodified, and `ruff check .` must stay clean.

## Acceptance criteria

- `app/api/routes.py` no longer exists.
- `from app.api.<module> import router` works for each of the seven modules above and each
  router contains exactly its routes from the table.
- The application built by `create_app()` serves the same routes (same methods, paths,
  handler names, tags and status codes) as before, from the new modules.
- `pytest` and `ruff check .` pass.
