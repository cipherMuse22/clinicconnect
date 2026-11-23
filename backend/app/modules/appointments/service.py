"""Booking rules. Routers stay thin; everything that must be atomic lives here."""
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment, AppointmentSlot
from app.modules.branches.models import BranchHours
from app.modules.inventory.service import service_in_stock
from app.modules.notifications.service import notify
from app.modules.services.models import BranchService, Service

# no 0/O/1/I so references are easy to read out over the phone (FR-027)
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def now_local() -> datetime:
    """Current clinic time as a naive datetime (slots are stored as local date + time)."""
    return datetime.now(ZoneInfo(get_settings().clinic_timezone)).replace(tzinfo=None)


def new_reference() -> str:
    return "APT-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))


def slot_start(slot: AppointmentSlot) -> datetime:
    return datetime.combine(slot.slot_date, slot.start_time)


def describe(appt: Appointment, slot: AppointmentSlot | None = None) -> str:
    """One-line summary used in notifications. Contains no clinical information."""
    slot = slot or appt.slot
    bs = slot.branch_service
    return (
        f"{bs.service.service_name} at {bs.branch.branch_name} on {slot.slot_date:%a %d %b %Y} "
        f"at {slot.start_time:%H:%M} (ref {appt.appointment_reference})"
    )


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


# ---------------------------------------------------------------- slot generation


def generate_slots(
    db: Session, bs: BranchService, service: Service, from_date: date, to_date: date, capacity: int
) -> int:
    """Create slots from branch opening hours, one every `estimated_duration_min` minutes.

    Skips closed days, slots already in the past and slots that already exist, so it is safe to re-run.
    """
    hours = {h.day_of_week: h for h in db.scalars(select(BranchHours).where(BranchHours.branch_id == bs.branch_id))}
    existing = {
        (r[0], r[1])
        for r in db.execute(
            select(AppointmentSlot.slot_date, AppointmentSlot.start_time).where(
                AppointmentSlot.branch_service_id == bs.branch_service_id,
                AppointmentSlot.slot_date >= from_date,
                AppointmentSlot.slot_date <= to_date,
            )
        )
    }
    now = now_local()
    step = timedelta(minutes=service.estimated_duration_min)
    created = 0
    day = from_date
    while day <= to_date:
        h = hours.get(day.weekday())
        if h:
            cur = datetime.combine(day, h.open_time)
            close = datetime.combine(day, h.close_time)
            while cur + step <= close:
                if cur > now and (day, cur.time()) not in existing:
                    db.add(
                        AppointmentSlot(
                            branch_service_id=bs.branch_service_id,
                            slot_date=day,
                            start_time=cur.time(),
                            end_time=(cur + step).time(),
                            capacity=capacity,
                        )
                    )
                    created += 1
                cur += step
        day += timedelta(days=1)
    db.flush()
    return created


# ---------------------------------------------------------------- guarded capacity updates


def _take_place(db: Session, slot_id: int) -> bool:
    """Atomically add one booking. False if the slot is full. One UPDATE, so no race is possible."""
    res = db.execute(
        update(AppointmentSlot)
        .where(AppointmentSlot.slot_id == slot_id, AppointmentSlot.booked_count < AppointmentSlot.capacity)
        .values(booked_count=AppointmentSlot.booked_count + 1)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


def _release_place(db: Session, slot_id: int) -> None:
    db.execute(
        update(AppointmentSlot)
        .where(AppointmentSlot.slot_id == slot_id, AppointmentSlot.booked_count > 0)
        .values(booked_count=AppointmentSlot.booked_count - 1)
        .execution_options(synchronize_session=False)
    )


# ---------------------------------------------------------------- checks


def load_bookable_slot(db: Session, slot_id: int) -> AppointmentSlot:
    """Return the slot if it can currently be booked, else raise a clear error (FR-021, FR-051)."""
    slot = db.get(AppointmentSlot, slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
    bs = slot.branch_service
    if bs.branch.status != "active" or bs.service.status != "active" or bs.availability_status != "available":
        raise _conflict("This service is not available at this branch right now")
    if not service_in_stock(db, bs.branch_id, bs.service_id):  # FR-051
        raise _conflict("This service is temporarily unavailable at this branch")
    if slot_start(slot) <= now_local():
        raise _conflict("This time slot has already started")
    return slot


def _patient_already_holds(db: Session, patient_id: int, slot_id: int) -> bool:
    return (
        db.scalar(
            select(Appointment.appointment_id).where(
                Appointment.patient_id == patient_id,
                Appointment.slot_id == slot_id,
                Appointment.status != "cancelled",
            )
        )
        is not None
    )


def _inside_cutoff(slot: AppointmentSlot) -> bool:
    return slot_start(slot) - now_local() < timedelta(hours=get_settings().cancellation_cutoff_hours)


# ---------------------------------------------------------------- operations


def book_slot(db: Session, patient_id: int, slot_id: int, booked_by_staff_id: int | None = None) -> Appointment:
    slot = load_bookable_slot(db, slot_id)
    if _patient_already_holds(db, patient_id, slot_id):
        raise _conflict("You already have a booking for this time slot")
    if not _take_place(db, slot_id):
        db.rollback()
        raise _conflict("Sorry, this time slot is now full. Please choose another time.")
    appt = Appointment(
        appointment_reference=new_reference(),
        patient_id=patient_id,
        slot_id=slot_id,
        booked_by_staff_id=booked_by_staff_id,
    )
    db.add(appt)
    try:
        db.flush()
        notify(db, patient_id, "appointment_booked", f"Booked: {describe(appt)}.", appt.appointment_id)
        db.commit()  # place taken, appointment and notification saved together, or none of them
    except IntegrityError:
        db.rollback()
        raise _conflict("Could not complete the booking. Please try again.")
    return appt


def get_active_appointment(db: Session, appointment_id: int) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    return appt


def cancel_appointment(db: Session, appt: Appointment, reason: str | None, by_staff: bool) -> Appointment:
    if appt.status != "booked":
        raise _conflict(f"Only booked appointments can be cancelled (this one is {appt.status})")
    if not by_staff and _inside_cutoff(appt.slot):
        raise _conflict(
            f"Online cancellation closes {get_settings().cancellation_cutoff_hours} hours before the appointment. "
            "Please call the branch."
        )
    _release_place(db, appt.slot_id)  # FR-030
    appt.status = "cancelled"
    appt.cancelled_at = datetime.now().astimezone()
    appt.cancellation_reason = reason
    notify(db, appt.patient_id, "appointment_cancelled", f"Cancelled: {describe(appt)}.", appt.appointment_id)
    db.commit()
    return appt


def reschedule_appointment(db: Session, appt: Appointment, new_slot_id: int, by_staff: bool) -> Appointment:
    if appt.status != "booked":
        raise _conflict(f"Only booked appointments can be rescheduled (this one is {appt.status})")
    old_slot = appt.slot
    if new_slot_id == old_slot.slot_id:
        raise HTTPException(422, "Choose a different time slot")
    if not by_staff and _inside_cutoff(old_slot):
        raise _conflict(
            f"Online changes close {get_settings().cancellation_cutoff_hours} hours before the appointment. "
            "Please call the branch."
        )
    new_slot = load_bookable_slot(db, new_slot_id)
    if new_slot.branch_service_id != old_slot.branch_service_id:
        raise HTTPException(
            422,
            "A reschedule must stay at the same branch and service. Cancel and book a new appointment instead.",
        )
    if _patient_already_holds(db, appt.patient_id, new_slot_id):
        raise _conflict("You already have a booking for that time slot")

    # Update both slots in a fixed order (lowest id first) so two simultaneous reschedules cannot deadlock.
    for slot_id, delta in sorted([(new_slot_id, +1), (old_slot.slot_id, -1)]):
        if delta > 0:
            if not _take_place(db, slot_id):
                db.rollback()
                raise _conflict("Sorry, that time slot is full. Your original appointment is unchanged.")
        else:
            _release_place(db, slot_id)
    appt.slot_id = new_slot_id
    try:
        notify(db, appt.patient_id, "appointment_rescheduled", f"Rescheduled to {describe(appt, new_slot)}.", appt.appointment_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("Could not reschedule. Please try again.")
    db.refresh(appt)
    return appt
