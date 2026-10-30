"""HTTP routes for every Rentwise resource.

Handlers are thin: they parse input, call the service layer and return models. Domain
errors are translated to HTTP responses by the handlers in ``app.errors``.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.clock import Clock
from app.models import (
    Availability,
    Category,
    Coupon,
    CouponCreate,
    Customer,
    CustomerCreate,
    CustomerTier,
    Invoice,
    Item,
    ItemCreate,
    ItemPage,
    ItemStatusUpdate,
    Reservation,
    ReservationCreate,
    ReservationStatus,
    ReturnReceipt,
    ReturnRequest,
    RevenueReport,
    UtilizationReport,
)
from app.services import (
    availability,
    catalog,
    customers,
    invoices,
    pricing,
    reports,
    reservations,
    returns,
)
from app.storage import Store

router = APIRouter()


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


StoreDep = Annotated[Store, Depends(get_store)]
ClockDep = Annotated[Clock, Depends(get_clock)]


# --- health ----------------------------------------------------------------------------


@router.get("/health", tags=["meta"])
def health(clock: ClockDep) -> dict[str, str]:
    return {"status": "ok", "today": clock.today().isoformat()}


# --- catalog ---------------------------------------------------------------------------


@router.get("/categories", response_model=list[Category], tags=["catalog"])
def list_categories(store: StoreDep) -> list[Category]:
    return catalog.list_categories(store)


@router.get("/items", response_model=ItemPage, tags=["catalog"])
def list_items(
    store: StoreDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=catalog.MAX_PAGE_SIZE)] = catalog.DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemPage:
    return catalog.list_items(store, q=q, category=category, limit=limit, offset=offset)


@router.post("/items", response_model=Item, status_code=status.HTTP_201_CREATED, tags=["catalog"])
def create_item(store: StoreDep, data: ItemCreate) -> Item:
    return catalog.create_item(store, data)


@router.get("/items/{item_id}", response_model=Item, tags=["catalog"])
def get_item(store: StoreDep, item_id: int) -> Item:
    return catalog.get_item(store, item_id)


@router.post("/items/{item_id}/status", response_model=Item, tags=["catalog"])
def set_item_status(store: StoreDep, item_id: int, data: ItemStatusUpdate) -> Item:
    return catalog.set_item_status(store, item_id, data.status)


# --- customers -------------------------------------------------------------------------


@router.get("/customers", response_model=list[Customer], tags=["customers"])
def list_customers(store: StoreDep, tier: CustomerTier | None = None) -> list[Customer]:
    return customers.list_customers(store, tier=tier)


@router.post(
    "/customers",
    response_model=Customer,
    status_code=status.HTTP_201_CREATED,
    tags=["customers"],
)
def create_customer(store: StoreDep, data: CustomerCreate) -> Customer:
    return customers.create_customer(store, data)


@router.get("/customers/{customer_id}", response_model=Customer, tags=["customers"])
def get_customer(store: StoreDep, customer_id: int) -> Customer:
    return customers.get_customer(store, customer_id)


# --- coupons ---------------------------------------------------------------------------


@router.get("/coupons", response_model=list[Coupon], tags=["pricing"])
def list_coupons(store: StoreDep) -> list[Coupon]:
    return pricing.list_coupons(store)


@router.post(
    "/coupons", response_model=Coupon, status_code=status.HTTP_201_CREATED, tags=["pricing"]
)
def create_coupon(store: StoreDep, data: CouponCreate) -> Coupon:
    return pricing.create_coupon(store, data)


# --- availability ----------------------------------------------------------------------


@router.get("/availability", response_model=Availability, tags=["reservations"])
def get_availability(store: StoreDep, item_id: int, start: date, end: date) -> Availability:
    return availability.check_availability(store, item_id, start, end)


# --- reservations ----------------------------------------------------------------------


@router.get("/reservations", response_model=list[Reservation], tags=["reservations"])
def list_reservations(
    store: StoreDep,
    customer_id: int | None = None,
    item_id: int | None = None,
    status: ReservationStatus | None = None,
) -> list[Reservation]:
    return reservations.list_reservations(
        store, customer_id=customer_id, item_id=item_id, status=status
    )


@router.post(
    "/reservations",
    response_model=Reservation,
    status_code=status.HTTP_201_CREATED,
    tags=["reservations"],
)
def create_reservation(store: StoreDep, clock: ClockDep, data: ReservationCreate) -> Reservation:
    return reservations.create_reservation(store, clock, data)


@router.get("/reservations/{reservation_id}", response_model=Reservation, tags=["reservations"])
def get_reservation(store: StoreDep, reservation_id: int) -> Reservation:
    return reservations.get_reservation(store, reservation_id)


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=Reservation,
    tags=["reservations"],
)
def cancel_reservation(store: StoreDep, reservation_id: int) -> Reservation:
    return reservations.cancel_reservation(store, reservation_id)


@router.post(
    "/reservations/{reservation_id}/return",
    response_model=ReturnReceipt,
    tags=["reservations"],
)
def return_reservation(
    store: StoreDep,
    clock: ClockDep,
    reservation_id: int,
    data: ReturnRequest | None = None,
) -> ReturnReceipt:
    return returns.return_reservation(store, clock, reservation_id, data or ReturnRequest())


@router.get(
    "/reservations/{reservation_id}/invoice",
    response_model=Invoice,
    tags=["reservations"],
)
def get_invoice(store: StoreDep, reservation_id: int) -> Invoice:
    return invoices.get_invoice(store, reservation_id)


# --- reports ---------------------------------------------------------------------------


@router.get("/reports/revenue", response_model=RevenueReport, tags=["reports"])
def revenue_report(store: StoreDep, start: date, end: date) -> RevenueReport:
    return reports.revenue_report(store, start, end)


@router.get("/reports/utilization", response_model=UtilizationReport, tags=["reports"])
def utilization_report(store: StoreDep, start: date, end: date) -> UtilizationReport:
    return reports.utilization_report(store, start, end)
