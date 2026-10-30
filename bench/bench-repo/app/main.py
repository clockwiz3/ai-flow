"""Application factory."""

from fastapi import FastAPI

from app import __version__
from app.api.routes import router
from app.clock import Clock, SystemClock
from app.errors import register_exception_handlers
from app.storage import Store


def create_app(store: Store | None = None, clock: Clock | None = None) -> FastAPI:
    """Build a Rentwise application.

    ``store`` defaults to a freshly seeded in-memory store and ``clock`` to the system
    clock; tests pass their own instances to control data and "today".
    """
    app = FastAPI(
        title="Rentwise",
        version=__version__,
        description="Equipment rental shop: tools, camping and photo gear.",
    )
    app.state.store = store if store is not None else Store.seeded()
    app.state.clock = clock if clock is not None else SystemClock()
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
