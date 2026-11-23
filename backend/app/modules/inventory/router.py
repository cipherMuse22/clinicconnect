from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import ensure_branch_access, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Staff
from app.modules.branches.models import Branch
from app.modules.inventory import service as inv
from app.modules.inventory.models import BranchStock, InventoryItem, ServiceItem, StockMovement
from app.modules.services.models import Service

router = APIRouter(tags=["inventory"])

STOCK_EDITORS = ("inventory_manager", "system_admin")
STOCK_VIEWERS = ("inventory_manager", "clinic_manager", "nurse", "system_admin")


# ------------------------------------------------------------------ schemas


class ItemIn(BaseModel):
    item_name: str = Field(min_length=2, max_length=120)
    item_category: str | None = Field(default=None, max_length=60)
    unit: str = Field(min_length=1, max_length=30)


class ItemOut(ItemIn):
    item_id: int
    model_config = {"from_attributes": True}


class StockCreate(BaseModel):
    item_id: int
    initial_quantity: int = Field(default=0, ge=0)
    minimum_quantity: int = Field(default=0, ge=0)


class StockUpdate(BaseModel):
    minimum_quantity: int | None = Field(default=None, ge=0)
    availability_status: Literal["available", "unavailable"] | None = None


class StockOut(BaseModel):
    branch_id: int
    item_id: int
    item_name: str
    item_category: str | None
    unit: str
    quantity: int
    minimum_quantity: int
    availability_status: str
    low_stock: bool  # FR-049: quantity is below the configured minimum
    updated_at: datetime


class MovementIn(BaseModel):
    movement_type: Literal["received", "used", "adjusted"]
    quantity: int = Field(description="received/used: a positive number. adjusted: positive or negative, not zero.")
    reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def check(self):
        if self.quantity == 0:
            raise ValueError("quantity cannot be zero")
        if self.movement_type in ("received", "used") and self.quantity < 0:
            raise ValueError("quantity must be positive for received and used")
        if self.movement_type == "adjusted" and not (self.reason and self.reason.strip()):
            raise ValueError("a reason is required for an adjustment")
        return self


class MovementOut(BaseModel):
    movement_id: int
    movement_type: str
    quantity_change: int
    quantity_after: int
    reason: str | None
    staff_id: int
    created_at: datetime
    model_config = {"from_attributes": True}


class ServiceItemIn(BaseModel):
    quantity_per_service: int = Field(default=1, ge=1, le=1000)


class ServiceItemOut(BaseModel):
    item_id: int
    item_name: str
    unit: str
    quantity_per_service: int


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def stock_out(s: BranchStock) -> StockOut:
    return StockOut(
        branch_id=s.branch_id, item_id=s.item_id, item_name=s.item.item_name, item_category=s.item.item_category,
        unit=s.item.unit, quantity=s.quantity, minimum_quantity=s.minimum_quantity,
        availability_status=s.availability_status, low_stock=s.quantity < s.minimum_quantity, updated_at=s.updated_at,
    )


def _branch_check(db: Session, staff: Staff, branch_id: int) -> None:
    if db.get(Branch, branch_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    ensure_branch_access(staff, branch_id)  # FR-017, section 3.5: assigned branches only


def _stock_or_404(db: Session, branch_id: int, item_id: int) -> BranchStock:
    s = db.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.item_id == item_id))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This branch does not hold that item")
    return s


# ------------------------------------------------------------------ item catalogue


@router.get("/inventory/items", response_model=list[ItemOut])
def list_items(db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*STOCK_VIEWERS))):
    return db.scalars(select(InventoryItem).order_by(InventoryItem.item_name)).all()


@router.post("/inventory/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    data: ItemIn, request: Request, db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*STOCK_EDITORS))
):
    name = data.item_name.strip()
    if db.scalar(select(InventoryItem.item_id).where(InventoryItem.item_name == name)):
        raise HTTPException(409, "An item with this name already exists")
    item = InventoryItem(item_name=name, item_category=data.item_category, unit=data.unit.strip())
    db.add(item)
    db.flush()
    write_audit(db, actor_staff_id=staff.staff_id, action="inventory.item.create", entity_type="inventory_item",
                entity_id=item.item_id, details={"item_name": name}, ip_address=_ip(request))
    db.commit()
    return item


# ------------------------------------------------------------------ branch stock


@router.get("/branches/{branch_id}/stock", response_model=list[StockOut])
def branch_stock(branch_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*STOCK_VIEWERS))):
    """FR-047. Stock figures are an operational aid: staff must verify real stock before providing a service."""
    _branch_check(db, staff, branch_id)
    rows = db.scalars(
        select(BranchStock).join(InventoryItem).where(BranchStock.branch_id == branch_id).order_by(InventoryItem.item_name)
    ).all()
    return [stock_out(s) for s in rows]


@router.get("/branches/{branch_id}/stock/low", response_model=list[StockOut])
def low_stock(branch_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*STOCK_VIEWERS))):
    """FR-049: items below their minimum level."""
    _branch_check(db, staff, branch_id)
    rows = db.scalars(
        select(BranchStock).join(InventoryItem)
        .where(BranchStock.branch_id == branch_id, BranchStock.quantity < BranchStock.minimum_quantity)
        .order_by(InventoryItem.item_name)
    ).all()
    return [stock_out(s) for s in rows]


@router.post("/branches/{branch_id}/stock", response_model=StockOut, status_code=status.HTTP_201_CREATED)
def add_stock_record(
    branch_id: int, data: StockCreate, request: Request, db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*STOCK_EDITORS)),
):
    """Start tracking an item at a branch."""
    _branch_check(db, staff, branch_id)
    if db.get(InventoryItem, data.item_id) is None:
        raise HTTPException(404, "Item not found")
    stock = BranchStock(branch_id=branch_id, item_id=data.item_id, quantity=0, minimum_quantity=data.minimum_quantity)
    db.add(stock)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This branch already tracks that item")
    if data.initial_quantity:
        inv.apply_movement(db, stock, staff.staff_id, "received", data.initial_quantity, "Initial stock")
    write_audit(db, actor_staff_id=staff.staff_id, action="inventory.stock.create", entity_type="branch_stock",
                entity_id=stock.branch_stock_id, details={"branch_id": branch_id, "item_id": data.item_id}, ip_address=_ip(request))
    db.commit()
    db.refresh(stock)
    return stock_out(stock)


@router.patch("/branches/{branch_id}/stock/{item_id}", response_model=StockOut)
def update_stock_settings(
    branch_id: int, item_id: int, data: StockUpdate, request: Request, db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*STOCK_EDITORS)),
):
    """Change the minimum level, or mark the item unavailable or available again."""
    _branch_check(db, staff, branch_id)
    stock = _stock_or_404(db, branch_id, item_id)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(stock, k, v)
    write_audit(db, actor_staff_id=staff.staff_id, action="inventory.stock.update", entity_type="branch_stock",
                entity_id=stock.branch_stock_id, details=changes, ip_address=_ip(request))
    db.commit()
    return stock_out(stock)


@router.post("/branches/{branch_id}/stock/{item_id}/movements", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def record_movement(
    branch_id: int, item_id: int, data: MovementIn, db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*STOCK_EDITORS)),
):
    """FR-048: record stock received, used, or adjusted. Stock can never go below zero."""
    _branch_check(db, staff, branch_id)
    stock = _stock_or_404(db, branch_id, item_id)
    change = -data.quantity if data.movement_type == "used" else data.quantity
    movement = inv.apply_movement(db, stock, staff.staff_id, data.movement_type, change, data.reason)
    db.commit()
    return movement


@router.get("/branches/{branch_id}/stock/{item_id}/movements", response_model=list[MovementOut])
def movement_history(
    branch_id: int, item_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*STOCK_VIEWERS)),
):
    _branch_check(db, staff, branch_id)
    stock = _stock_or_404(db, branch_id, item_id)
    return db.scalars(
        select(StockMovement).where(StockMovement.branch_stock_id == stock.branch_stock_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.movement_id.desc()).limit(200)
    ).all()


# ------------------------------------------------------------------ which stock a service uses (FR-051)


@router.get("/services/{service_id}/items", response_model=list[ServiceItemOut])
def service_items(service_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*STOCK_VIEWERS))):
    rows = db.scalars(select(ServiceItem).where(ServiceItem.service_id == service_id)).all()
    return [ServiceItemOut(item_id=r.item_id, item_name=r.item.item_name, unit=r.item.unit, quantity_per_service=r.quantity_per_service) for r in rows]


@router.put("/services/{service_id}/items/{item_id}", response_model=ServiceItemOut)
def link_service_item(
    service_id: int, item_id: int, data: ServiceItemIn, request: Request, db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    service, item = db.get(Service, service_id), db.get(InventoryItem, item_id)
    if service is None or item is None:
        raise HTTPException(404, "Service or item not found")
    link = db.scalar(select(ServiceItem).where(ServiceItem.service_id == service_id, ServiceItem.item_id == item_id))
    if link is None:
        link = ServiceItem(service_id=service_id, item_id=item_id)
        db.add(link)
    link.quantity_per_service = data.quantity_per_service
    write_audit(db, actor_staff_id=admin.staff_id, action="service_item.set", entity_type="service",
                entity_id=service_id, details={"item_id": item_id, "quantity_per_service": data.quantity_per_service}, ip_address=_ip(request))
    db.commit()
    return ServiceItemOut(item_id=item.item_id, item_name=item.item_name, unit=item.unit, quantity_per_service=link.quantity_per_service)


@router.delete("/services/{service_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_service_item(
    service_id: int, item_id: int, request: Request, db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    link = db.scalar(select(ServiceItem).where(ServiceItem.service_id == service_id, ServiceItem.item_id == item_id))
    if link is None:
        raise HTTPException(404, "That service does not use that item")
    db.delete(link)
    write_audit(db, actor_staff_id=admin.staff_id, action="service_item.remove", entity_type="service",
                entity_id=service_id, details={"item_id": item_id}, ip_address=_ip(request))
    db.commit()
