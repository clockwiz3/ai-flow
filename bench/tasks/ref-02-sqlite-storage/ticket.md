# Refactor: move the repositories from Python dicts to SQLite

**Type:** refactoring (no functional change)
**Area:** `app/storage.py` (plus wording in `README.md` / docstrings)

## Motivation

All data lives in Python dictionaries inside the repositories of `app/storage.py`, so
everything is lost on restart and nothing can be inspected with ordinary tools. As a first
step towards a real database we want the repositories to be backed by **SQLite**, behind the
very same repository interface, so that no service and no route has to change.

## Target structure

### Storage engine

- Use the standard-library `sqlite3` module only. **No new dependencies** (no SQLAlchemy,
  no ORM, nothing added to `pyproject.toml`).
- `app/storage.py` must not keep entities in Python containers any more: no dict/list of
  models, no cache, no "write to SQLite but read from a dict". Every read goes to the
  database. All five repositories (categories, items, customers, reservations, coupons)
  are SQLite tables.
- The schema is created by the store itself when it opens a database (use
  `CREATE TABLE IF NOT EXISTS`, so opening an existing database file works too).

### `Store` contract

- `Store(db_path: str = ":memory:")` opens (`sqlite3.connect(db_path, ...)`) its own
  database and creates the schema. `Store()` therefore gives a **fresh, private, empty
  in-memory database**: two `Store()` instances never see each other's data.
- `store.connection` is the `sqlite3.Connection` used by all repositories of that store.
- `Store.seeded()` (optionally `Store.seeded(db_path)`) still returns a new store loaded
  with the demo data via `load_seed(store)`; `load_seed` keeps its signature.
- The repositories stay available as the attributes `categories`, `items`, `customers`,
  `reservations` and `coupons` (they need not be dataclass fields any more).
- Every write is committed immediately (autocommit): a second `Store` opened on the same
  database **file** must see everything the first one wrote, and continue the id sequence.
- The application is served from FastAPI's thread pool (and from `TestClient`), so the
  connection must be usable from threads other than the one that created it.
- `create_app(store=None, clock=None)` keeps its signature; with `store=None` it uses
  `Store.seeded()` (a private in-memory database per application).

### Repository interface (unchanged - the services depend on it)

Every repository keeps exactly today's public methods and semantics:

| Method | Semantics |
| --- | --- |
| `insert(entity)` | add a new entity; raises **`KeyError`** if the key already exists |
| `save(entity)` | insert or replace |
| `get(key)` | the entity or `None` (coupons: code is matched after `strip().upper()`) |
| `all()` | all entities **ordered by key** |
| `__iter__`, `__len__`, `__contains__(key)` | as today |
| `allocate_id()` (int-id repositories) | reserves and returns the next id; consecutive calls return consecutive ids, an id is never handed out twice |
| `create(data)` (items, customers, coupons) | as today |
| `customers.by_email(email)` | case-insensitive lookup (`strip().lower()`) |
| `reservations.for_item(id)`, `for_customer(id)` | ordered by reservation id |

**Id assignment must be identical to today:** ids start at 1; inserting an entity with an
explicit id `n` moves the sequence to at least `n + 1`; ids are never reused.

### Round-tripping

Entities returned by the repositories must be equal to what was stored, with the same Python
types:

- money (`Decimal`) is stored as TEXT and comes back **exactly** - `Decimal("12.50")` must not
  become `Decimal("12.5")`, `Decimal("200")` must not become `Decimal("200.0")` (no REAL /
  float columns for money);
- dates are stored as ISO TEXT and come back as `datetime.date` (not strings), `None`
  stays `None`;
- enums come back as the enum members (`item.status is ItemStatus.MAINTENANCE` - the
  services compare with `is`);
- booleans come back as `bool`.

### Docs

Update `README.md` (intro sentence, the `create_app` paragraph and the layout table) so it
no longer describes the storage as in-memory dictionaries, and document `Store(db_path)`.

## Constraints

- **Behaviour must not change.** Every endpoint returns exactly the same status codes,
  bodies and error messages as before for every input. This is a pure refactoring: do not
  fix or change any business logic while you are in there, even if something looks odd.
- Services (`app/services/`) and routes (`app/api/`) should not need changes; if you touch
  them, behaviour must stay identical.
- All existing tests must keep passing **unmodified** (including `tests/conftest.py`), and
  `ruff check .` must stay clean.

## Acceptance criteria

- `app/storage.py` uses `sqlite3`; no repository keeps entities in Python containers.
- `Store()` / `Store(":memory:")` / `Store(db_path=...)` work as described; separate
  in-memory stores are isolated; stores on the same file share data and the id sequence.
- Repository methods behave as in the table above, including `KeyError` on duplicate
  `insert`, ordering, case-insensitive coupon/e-mail lookups and id assignment.
- `Decimal`, `date`, enum and `bool` values round-trip exactly.
- The API behaves exactly as before; `pytest` and `ruff check .` pass.
