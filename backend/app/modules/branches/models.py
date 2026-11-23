from datetime import time

from sqlalchemy import ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Branch(Base):
    __tablename__ = "branch"

    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    hours: Mapped[list["BranchHours"]] = relationship(
        back_populates="branch", cascade="all, delete-orphan", order_by="BranchHours.day_of_week"
    )


class BranchHours(Base):
    """One row per open day. A day with no row means the branch is closed. 0 = Monday ... 6 = Sunday."""

    __tablename__ = "branch_hours"
    __table_args__ = (UniqueConstraint("branch_id", "day_of_week"),)

    branch_hours_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)

    branch: Mapped[Branch] = relationship(back_populates="hours")
