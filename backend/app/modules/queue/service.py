"""Check-in and queue rules (FR-032 to FR-040, BR-005 to BR-007)."""
import hashlib
import hmac
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.accounts.models import Membership
from app.modules.appointments.models import Appointment, AppointmentSlot
from app.modules.appointments.service import now_local, slot_start
from app.modules.notifications.service import notify
from app.modules.queue.models import QueueCounter, QueueEntry, VisitRecord
from app.modules.services.models import BranchService, Service

WAITING_STATES = ("waiting",)  # only people still waiting count as "ahead"; a called patient has left the line

# allowed moves between queue statuses; "completed" only happens through complete_visit()
TRANSITIONS: dict[str, set[str]] = {
    "waiting": {"called", "skipped", "cancelled"},
    "called": {"in_service", "skipped", "cancelled", "waiting"},
    "in_service": set(),
    "skipped": {"waiting", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
SETTABLE = {"called", "in_service", "skipped", "cancelled", "waiting"}


def _conflict(msg) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


# ------------------------------------------------------------------ branch check-in code (the QR shown at reception)


def _sign(branch_id: int, day: date) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"checkin:{branch_id}:{day.isoformat()}".encode(), hashlib.sha256).hexdigest()[:20]


def make_checkin_token(branch_id: int) -> str:
    """Changes every day, so a photo of yesterday's code cannot be used to check in remotely."""
    return f"{branch_id}.{_sign(branch_id, now_local().date())}"


def branch_from_token(token: str) -> int:
    try:
        bid_text, sig = token.strip().split(".", 1)
        bid = int(bid_text)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid check-in code")
    if not hmac.compare_digest(sig, _sign(bid, now_local().date())):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired check-in code")
    return bid


# ------------------------------------------------------------------ finding the appointment to check in


def todays_booked(db: Session, patient_id: int, branch_id: int) -> list[Appointment]:
    return list(
        db.scalars(
            select(Appointment)
            .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
            .join(BranchService, BranchService.branch_service_id == AppointmentSlot.branch_service_id)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status == "booked",
                BranchService.branch_id == branch_id,
                AppointmentSlot.slot_date == now_local().date(),
            )
            .order_by(AppointmentSlot.start_time)
        )
    )


def pick_single(appts: list[Appointment]) -> Appointment:
    if not appts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No booked appointment found for today at this branch")
    if len(appts) > 1:
        refs = [a.appointment_reference for a in appts]
        raise _conflict(f"More than one appointment today. Check in with one of these references: {', '.join(refs)}")
    return appts[0]


def appointment_for_membership_qr(db: Session, qr_token: str, branch_id: int) -> Appointment:
    m = db.scalar(select(Membership).where(Membership.qr_token == qr_token))
    if m is None or m.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership QR code not recognised")
    return pick_single(todays_booked(db, m.patient_id, branch_id))


# ------------------------------------------------------------------ check in


def next_queue_number(db: Session, branch_id: int, day: date) -> int:
    """Atomically take the next number for this branch and day (BR-007).

    The UPDATE locks the counter row until the check-in commits, so simultaneous check-ins line up
    one after another. If the check-in later fails, the rollback also undoes the number: no gaps."""
    for _ in range(3):
        res = db.execute(
            update(QueueCounter)
            .where(QueueCounter.branch_id == branch_id, QueueCounter.queue_date == day)
            .values(last_number=QueueCounter.last_number + 1)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            return db.scalar(
                select(QueueCounter.last_number).where(QueueCounter.branch_id == branch_id, QueueCounter.queue_date == day)
            )
        try:  # first check-in of the day at this branch
            with db.begin_nested():
                db.add(QueueCounter(branch_id=branch_id, queue_date=day, last_number=1))
                db.flush()
            return 1
        except IntegrityError:
            continue  # someone else just created it: go round and increment instead
    raise _conflict("Could not check in just now. Please try again.")


def check_in(
    db: Session, appt: Appointment, branch_id: int, method: str, staff_id: int | None = None
) -> QueueEntry:
    by_staff = staff_id is not None
    slot = appt.slot
    bs = slot.branch_service
    if appt.status == "checked_in":
        raise _conflict("This appointment is already checked in")
    if appt.status != "booked":  # BR-005: cancelled, completed, no-show...
        raise _conflict(f"This appointment cannot be checked in (status: {appt.status})")
    if bs.branch_id != branch_id:  # BR-006
        raise _conflict(f"This appointment is for {bs.branch.branch_name}. Please check in there.")
    now = now_local()
    if slot.slot_date != now.date():
        raise _conflict("This appointment is not today")
    if not by_staff:
        opens = slot_start(slot) - timedelta(minutes=get_settings().checkin_window_minutes)
        closes = datetime.combine(slot.slot_date, slot.end_time) + timedelta(minutes=get_settings().checkin_grace_minutes)
        if now < opens:
            raise _conflict(f"Check-in opens at {opens:%H:%M}")
        if now > closes:
            raise _conflict("Check-in for this appointment has closed. Please speak to reception.")

    try:
        number = next_queue_number(db, branch_id, now.date())
        entry = QueueEntry(
            appointment_id=appt.appointment_id,
            branch_id=branch_id,
            queue_date=now.date(),
            queue_number=number,
            check_in_method=method,
            checked_in_by_staff_id=staff_id,
            check_in_time=datetime.now().astimezone(),
        )
        db.add(entry)
        db.flush()
    except IntegrityError:  # the same appointment was checked in by someone else a moment ago
        db.rollback()
        raise _conflict("This appointment is already checked in")
    appt.status = "checked_in"
    notify(
        db, appt.patient_id, "checked_in",
        f"You are checked in at {bs.branch.branch_name}. Your queue number is {entry.queue_number}.", appt.appointment_id,
    )
    db.commit()
    return entry


# ------------------------------------------------------------------ queue views


def queue_position(db: Session, entry: QueueEntry) -> tuple[int, int]:
    """(people_ahead, estimated_wait_minutes). People ahead = those still waiting with a lower number.
    The estimate is the sum of their booked service durations, so it is rough and must always be shown
    as an estimate (FR-040)."""
    if entry.queue_status != "waiting":
        return 0, 0
    rows = db.execute(
        select(Service.estimated_duration_min)
        .select_from(QueueEntry)
        .join(Appointment, Appointment.appointment_id == QueueEntry.appointment_id)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .join(BranchService, BranchService.branch_service_id == AppointmentSlot.branch_service_id)
        .join(Service, Service.service_id == BranchService.service_id)
        .where(
            QueueEntry.branch_id == entry.branch_id,
            QueueEntry.queue_date == entry.queue_date,
            QueueEntry.queue_number < entry.queue_number,
            QueueEntry.queue_status.in_(WAITING_STATES),
        )
    ).all()
    return len(rows), sum(r[0] for r in rows)


# ------------------------------------------------------------------ staff actions


def _notify_called(db: Session, entry: QueueEntry) -> None:
    """FR-044: tell the patient it is their turn."""
    appt = entry.appointment
    notify(
        db, appt.patient_id, "queue_called",
        f"It's your turn. Queue number {entry.queue_number} at {appt.slot.branch_service.branch.branch_name}.",
        appt.appointment_id,
    )


def call_next(db: Session, branch_id: int, staff_id: int) -> QueueEntry:
    """Call the lowest-numbered waiting patient. The claim is a guarded UPDATE, so two nurses
    pressing the button at once can never call the same person."""
    today = now_local().date()
    for _ in range(5):
        candidate = db.scalar(
            select(QueueEntry.queue_id)
            .where(QueueEntry.branch_id == branch_id, QueueEntry.queue_date == today, QueueEntry.queue_status == "waiting")
            .order_by(QueueEntry.queue_number)
            .limit(1)
        )
        if candidate is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nobody is waiting")
        res = db.execute(
            update(QueueEntry)
            .where(QueueEntry.queue_id == candidate, QueueEntry.queue_status == "waiting")
            .values(queue_status="called", called_at=datetime.now().astimezone(), called_by_staff_id=staff_id)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            entry = db.get(QueueEntry, candidate, populate_existing=True)
            _notify_called(db, entry)
            db.commit()
            return entry
        db.rollback()  # someone else took them first: try the next person
    raise _conflict("Could not call the next patient. Please try again.")


def change_status(db: Session, entry: QueueEntry, new_status: str, staff_id: int, is_nurse: bool) -> QueueEntry:
    if new_status not in SETTABLE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Use the complete-visit action to finish a visit" if new_status == "completed" else "Unknown status",
        )
    if new_status not in TRANSITIONS[entry.queue_status]:
        raise _conflict(f"Cannot move from {entry.queue_status} to {new_status}")
    if new_status == "in_service" and not is_nurse:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a nurse can start a service")

    now = datetime.now().astimezone()
    entry.queue_status = new_status
    if new_status == "called":
        entry.called_at, entry.called_by_staff_id = now, staff_id
        _notify_called(db, entry)
    elif new_status == "in_service":
        entry.started_at = now
        entry.appointment.status = "in_progress"
        entry.appointment.assigned_staff_id = staff_id
    elif new_status == "cancelled":
        entry.appointment.status = "no_show"  # checked in but left without being seen
    db.commit()
    return entry


def complete_visit(db: Session, entry: QueueEntry, staff_id: int) -> QueueEntry:
    if entry.queue_status != "in_service":
        raise _conflict(f"Only a patient who is in service can be completed (this one is {entry.queue_status})")
    now = datetime.now().astimezone()
    entry.queue_status = "completed"
    entry.completed_at = now
    entry.appointment.status = "completed"
    db.add(VisitRecord(appointment_id=entry.appointment_id, staff_id=staff_id, completed_at=now))
    db.commit()
    return entry
