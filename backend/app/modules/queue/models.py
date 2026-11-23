from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.appointments.models import Appointment

# queue_status: waiting, called, in_service, completed, skipped, cancelled   (FR-038)


class QueueEntry(Base):
    """One entry per checked-in appointment. Numbers restart each day at each branch (BR-007)."""

    __tablename__ = "queue_entry"
    __table_args__ = (
        UniqueConstraint("branch_id", "queue_date", "queue_number"),
        Index("ix_queue_branch_date", "branch_id", "queue_date"),
    )

    queue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.appointment_id"), unique=True, nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), nullable=False)
    queue_date: Mapped[date] = mapped_column(Date, nullable=False)
    queue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_status: Mapped[str] = mapped_column(String(20), default="waiting", nullable=False)
    check_in_method: Mapped[str] = mapped_column(String(20), nullable=False)  # branch_qr, reference, membership_qr
    checked_in_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.staff_id"))
    called_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.staff_id"))
    check_in_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    appointment: Mapped[Appointment] = relationship()


class QueueCounter(Base):
    """Last number issued per branch per day. Incremented with a single UPDATE, which serialises
    simultaneous check-ins so numbers are unique and have no gaps."""

    __tablename__ = "queue_counter"

    branch_id: Mapped[int] = mapped_column(ForeignKey("branch.branch_id"), primary_key=True)
    queue_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class VisitRecord(Base):
    """Administrative record that a visit took place. Clinical notes are a separate, restricted table (later phase)."""

    __tablename__ = "visit_record"

    visit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.appointment_id"), unique=True, nullable=False)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
