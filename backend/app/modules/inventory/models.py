from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InventoryItem(Base):
    """A kind of stock (for example one vaccine dose or a test strip). Shared by all branches."""

    __tablename__ = "inventory_item"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    item_category: Mapped[str | None] = mapped_column(String(60))
    unit: Mapped[str] = mapped_column(String(30), nullable=False)


class BranchStock(Base):
    """How many of an item one branch holds (FR-047). Quantity changes only through guarded updates."""

    __tablename__ = "branch_stock"
    __table_args__ = (
        UniqueConstraint("branch_id", "item_id"),
        CheckConstraint("quantity >= 0 AND minimum_quantity >= 0", name="ck_stock_not_negative"),
    )

    branch_stock_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.item_id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minimum_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    availability_status: Mapped[str] = mapped_column(String(20), default="available", nullable=False)  # available | unavailable
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    item: Mapped[InventoryItem] = relationship()


class StockMovement(Base):
    """Every change to a stock quantity, with who made it and why."""

    __tablename__ = "stock_movement"

    movement_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_stock_id: Mapped[int] = mapped_column(ForeignKey("branch_stock.branch_stock_id"), nullable=False, index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)  # received | used | adjusted
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ServiceItem(Base):
    """Which stock a service uses, so booking can avoid services that cannot be provided (FR-051)."""

    __tablename__ = "service_item"
    __table_args__ = (UniqueConstraint("service_id", "item_id"),)

    service_item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("service.service_id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.item_id"), nullable=False)
    quantity_per_service: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    item: Mapped[InventoryItem] = relationship()
