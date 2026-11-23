from datetime import date, datetime, time, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Time, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.accounts.models import Patient
from app.modules.services.models import BranchService

# Appointment statuses: booked, checked_in, in_progress, completed, cancelled, no_show
ACTIVE_STATUSES = ("booked", "checked_in", "in_progress")


class AppointmentSlot(Base):
    """A bookable time window for one service at one branch (BR-004).

    booked_count is only ever changed by guarded UPDATE statements, so two people can never
    take the last place (FR-026, NFR-014). The CHECK constraint is the database-level safety net.
    """

    __tablename__ = "appointment_slot"
    __table_args__ = (
        UniqueConstraint("branch_service_id", "slot_date", "start_time"),
        CheckConstraint("capacity > 0 AND booked_count >= 0 AND booked_count <= capacity", name="ck_slot_capacity"),
    )

    slot_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_service_id: Mapped[int] = mapped_column(ForeignKey("branch_service.branch_service_id"), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    booked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    branch_service: Mapped[BranchService] = relationship()


class Appointment(Base):
    """Branch and service come from the slot, so an appointment always has exactly one patient,
    one branch and one service (BR-003)."""

    __tablename__ = "appointment"
    __table_args__ = (
        # a patient cannot hold the same slot twice, but may rebook it after cancelling
        Index(
            "uq_active_booking_per_patient_slot",
            "patient_id",
            "slot_id",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
            sqlite_where=text("status <> 'cancelled'"),
        ),
    )

    appointment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_reference: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id"), nullable=False, index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("appointment_slot.slot_id"), nullable=False, index=True)
    assigned_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.staff_id"))
    booked_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.staff_id"))
    status: Mapped[str] = mapped_column(String(20), default="booked", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))

    patient: Mapped[Patient] = relationship()
    slot: Mapped[AppointmentSlot] = relationship()
