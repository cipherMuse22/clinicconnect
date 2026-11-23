"""Appointment reminders (FR-042). Run on a schedule, and safe to run as often as you like."""
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.appointments.models import Appointment, AppointmentSlot
from app.modules.appointments.service import describe, now_local, slot_start
from app.modules.notifications.models import Notification
from app.modules.notifications.service import notify

log = logging.getLogger("clinicconnect.reminders")


def send_due_reminders(db: Session) -> int:
    """Remind patients whose booked appointment starts within the next `reminder_hours_before` hours.

    One reminder per booking. If the appointment is rescheduled afterwards, a fresh reminder is sent
    for the new time."""
    now = now_local()
    horizon = now + timedelta(hours=get_settings().reminder_hours_before)
    candidates = [
        a
        for a in db.scalars(
            select(Appointment)
            .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
            .where(
                Appointment.status == "booked",
                AppointmentSlot.slot_date >= now.date(),
                AppointmentSlot.slot_date <= horizon.date(),
            )
        )
        if now < slot_start(a.slot) <= horizon
    ]
    sent = 0
    for appt in candidates:
        last_change = db.scalar(
            select(func.max(Notification.sent_at)).where(
                Notification.appointment_id == appt.appointment_id,
                Notification.notification_type.in_(("appointment_booked", "appointment_rescheduled")),
            )
        )
        last_reminder = db.scalar(
            select(func.max(Notification.sent_at)).where(
                Notification.appointment_id == appt.appointment_id,
                Notification.notification_type == "appointment_reminder",
            )
        )
        if last_reminder is not None and (last_change is None or last_reminder >= last_change):
            continue  # already reminded about this version of the booking
        notify(db, appt.patient_id, "appointment_reminder", f"Reminder: {describe(appt)}.", appt.appointment_id)
        sent += 1
    db.commit()
    return sent


def run_scheduled_reminders() -> None:
    """Entry point for the background scheduler (opens its own database session)."""
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            n = send_due_reminders(db)
        if n:
            log.info("sent %s reminder(s)", n)
    except Exception:  # noqa: BLE001
        log.exception("reminder job failed")
