"""Domain exceptions and their mapping to HTTP responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base class for all business-rule errors raised by the service layer."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """A referenced entity does not exist."""

    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    """The request clashes with the current state (double booking, wrong status, ...)."""

    status_code = 409
    code = "conflict"


class InvalidRequestError(DomainError):
    """The request is well-formed but violates a business rule about its values."""

    status_code = 422
    code = "invalid_request"


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers translating ``DomainError`` subclasses into JSON errors."""
    app.add_exception_handler(DomainError, _domain_error_handler)
