from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.inventory.models import BranchStock, ServiceItem, StockMovement


def service_in_stock(db: Session, branch_id: int, service_id: int) -> bool:
    """FR-051. A service that uses no tracked stock is always fine. Otherwise every item it needs must be
    held by the branch, marked available, and in sufficient quantity. Stock is an operational aid:
    staff must still check real stock before providing the service."""
    needs = db.execute(
        select(ServiceItem.item_id, ServiceItem.quantity_per_service).where(ServiceItem.service_id == service_id)
    ).all()
    for item_id, per_service in needs:
        stock = db.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.item_id == item_id))
        if stock is None or stock.availability_status != "available" or stock.quantity < per_service:
            return False
    return True


def apply_movement(
    db: Session, stock: BranchStock, staff_id: int, movement_type: str, change: int, reason: str | None
) -> StockMovement:
    """Add `change` to the quantity in one guarded UPDATE, so stock can never go below zero,
    even when two people record movements at once."""
    res = db.execute(
        update(BranchStock)
        .where(BranchStock.branch_stock_id == stock.branch_stock_id, BranchStock.quantity + change >= 0)
        .values(quantity=BranchStock.quantity + change, updated_at=datetime.now().astimezone())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Not enough stock for that change")
    after = db.scalar(select(BranchStock.quantity).where(BranchStock.branch_stock_id == stock.branch_stock_id))
    movement = StockMovement(
        branch_stock_id=stock.branch_stock_id, staff_id=staff_id, movement_type=movement_type,
        quantity_change=change, quantity_after=after, reason=reason,
    )
    db.add(movement)
    return movement
