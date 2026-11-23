from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.modules.notifications import service as ns
from app.modules.notifications.models import Notification
from app.modules.notifications.reminders import send_due_reminders
from tests.test_appointments import book, first_slot, patient, staff_headers, world  # noqa: F401
from tests.test_queue import booked_patient, check_in, near_slot, nurse, reception

API = "/api/v1"


def inbox(client, headers, **params):
    return client.get(f"{API}/me/notifications", params=params, headers=headers).json()


def types(client, headers):
    return [n["notification_type"] for n in inbox(client, headers)]


# ------------------------------------------------------------------ events create notifications


def test_booking_cancel_reschedule_notify_the_patient(client, world):
    db = world["db"]
    h = patient(client)
    slots = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    appt = book(client, h, slots[0]["slot_id"]).json()  # FR-041
    first = inbox(client, h)[0]
    assert first["notification_type"] == "appointment_booked" and appt["appointment_reference"] in first["message"]
    assert "Flu vaccination" in first["message"] and "08:00" in first["message"] and first["read"] is False

    client.post(f"{API}/me/appointments/{appt['appointment_id']}/reschedule", json={"new_slot_id": slots[1]["slot_id"]}, headers=h)
    resched = inbox(client, h)[0]
    assert resched["notification_type"] == "appointment_rescheduled" and "08:30" in resched["message"]  # FR-043

    client.post(f"{API}/me/appointments/{appt['appointment_id']}/cancel", headers=h)
    assert types(client, h) == ["appointment_cancelled", "appointment_rescheduled", "appointment_booked"]  # newest first


def test_staff_cancel_also_notifies_the_patient(client, world):
    h = patient(client)
    appt = book(client, h, first_slot(world, client)["slot_id"]).json()
    rec = reception(client, world["db"])
    client.post(f"{API}/appointments/{appt['appointment_id']}/cancel", headers=rec)
    assert types(client, h)[0] == "appointment_cancelled"


def test_check_in_and_call_next_notify_the_patient(client, world):
    db = world["db"]
    a, _ = booked_patient(client, world, 1)
    check_in(client, a)
    msg = inbox(client, a)[0]
    assert msg["notification_type"] == "checked_in" and "queue number is 1" in msg["message"]
    client.post(f"{API}/branches/1/queue/call-next", headers=nurse(client, db))
    called = inbox(client, a)[0]
    assert called["notification_type"] == "queue_called" and "Queue number 1" in called["message"]  # FR-044


def test_failed_booking_leaves_no_notification(client, world):
    h = patient(client)
    slot = first_slot(world, client)
    book(client, h, slot["slot_id"])
    before = len(inbox(client, h))
    assert book(client, h, slot["slot_id"]).status_code == 409  # duplicate
    assert len(inbox(client, h)) == before


# ------------------------------------------------------------------ inbox


def test_read_state_unread_filter_and_count(client, world):
    h = patient(client)
    slots = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    book(client, h, slots[0]["slot_id"])
    book(client, h, slots[1]["slot_id"])
    assert client.get(f"{API}/me/notifications/unread-count", headers=h).json() == {"unread": 2}
    one = inbox(client, h)[0]["notification_id"]
    assert client.post(f"{API}/me/notifications/{one}/read", headers=h).json()["read"] is True
    assert client.get(f"{API}/me/notifications/unread-count", headers=h).json() == {"unread": 1}
    assert len(inbox(client, h, unread_only=True)) == 1
    assert client.post(f"{API}/me/notifications/read-all", headers=h).json() == {"marked_read": 1}
    assert inbox(client, h, unread_only=True) == []
    assert len(inbox(client, h, limit=1)) == 1 and len(inbox(client, h, limit=1, offset=1)) == 1


def test_patients_cannot_read_each_others_notifications(client, world):
    a, b = patient(client, 1), patient(client, 2)
    book(client, a, first_slot(world, client)["slot_id"])
    nid = inbox(client, a)[0]["notification_id"]
    assert inbox(client, b) == []
    assert client.post(f"{API}/me/notifications/{nid}/read", headers=b).status_code == 404
    assert client.get(f"{API}/me/notifications").status_code == 401
    assert client.get(f"{API}/me/notifications", headers=staff_headers(client, world["db"], "rec@clinic.example.com", "receptionist")).status_code == 401


# ------------------------------------------------------------------ reminders (FR-042)


def test_reminder_sent_once_for_soon_appointments_only(client, world):
    db = world["db"]
    h = patient(client)
    soon = near_slot(db, world["bs1"], minutes=180)
    book(client, h, soon.slot_id)
    book(client, h, first_slot(world, client)["slot_id"])  # ten days away: too early to remind
    assert send_due_reminders(db) == 1
    assert send_due_reminders(db) == 0  # not twice
    reminders = [n for n in inbox(client, h) if n["notification_type"] == "appointment_reminder"]
    assert len(reminders) == 1 and reminders[0]["message"].startswith("Reminder:")


def test_no_reminder_for_cancelled_appointment_and_new_reminder_after_reschedule(client, world):
    db = world["db"]
    h = patient(client)
    s1, s2 = near_slot(db, world["bs1"], minutes=180), near_slot(db, world["bs1"], minutes=200)
    appt = book(client, h, s1.slot_id).json()
    assert send_due_reminders(db) == 1
    client.post(f"{API}/me/appointments/{appt['appointment_id']}/reschedule", json={"new_slot_id": s2.slot_id}, headers=h)
    assert send_due_reminders(db) == 1  # the new time deserves a fresh reminder
    assert send_due_reminders(db) == 0
    client.post(f"{API}/me/appointments/{appt['appointment_id']}/cancel", headers=h)
    assert send_due_reminders(db) == 0


def test_reminder_job_endpoint_is_admin_only(client, world):
    db = world["db"]
    h = patient(client)
    book(client, h, near_slot(db, world["bs1"], minutes=180).slot_id)
    assert client.post(f"{API}/admin/jobs/send-reminders").status_code == 401
    assert client.post(f"{API}/admin/jobs/send-reminders", headers=reception(client, db)).status_code == 403
    admin = staff_headers(client, db, "admin@clinic.example.com", "system_admin")
    assert client.post(f"{API}/admin/jobs/send-reminders", headers=admin).json() == {"sent": 1}


# ------------------------------------------------------------------ providers (NFR-023)


def test_extra_channels_are_recorded_but_only_in_app_shows_in_inbox(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "notification_channels", ["in_app", "sms"])
    h = patient(client)
    book(client, h, first_slot(world, client)["slot_id"])
    channels = sorted(world["db"].scalars(select(Notification.channel)).all())
    assert channels == ["in_app", "sms"]
    assert len(inbox(client, h)) == 1


def test_failing_provider_never_blocks_the_booking(client, world, monkeypatch):
    class Boom:
        channel = "boom"

        def send(self, patient, message):
            raise RuntimeError("gateway down")

    ns.register_provider(Boom())
    monkeypatch.setattr(get_settings(), "notification_channels", ["in_app", "boom"])
    try:
        h = patient(client)
        assert book(client, h, first_slot(world, client)["slot_id"]).status_code == 201
        statuses = {n.channel: n.status for n in world["db"].scalars(select(Notification))}
        assert statuses == {"in_app": "sent", "boom": "failed"}
    finally:
        ns.PROVIDERS.pop("boom", None)
