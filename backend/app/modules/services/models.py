from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Service(Base):
    """A healthcare service the brand offers (FR-018, FR-019).

    status: 'active' or 'inactive' (system-wide switch, hides it everywhere).
    """

    __tablename__ = "service"

    service_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    estimated_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class BranchService(Base):
    """Which services a branch offers (FR-020) and whether each is available right now (FR-021, FR-050).

    availability_status: 'available' or 'unavailable'.
    """

    __tablename__ = "branch_service"
    __table_args__ = (UniqueConstraint("branch_id", "service_id"),)

    branch_service_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("service.service_id"), nullable=False)
    availability_status: Mapped[str] = mapped_column(String(20), default="available", nullable=False)

    service: Mapped[Service] = relationship()
