from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.appointments import service as svc
from app.modules.appointments.models import Appointment, AppointmentSlot
from app.modules.queue import service as q
from app.modules.queue.models import QueueEntry, VisitRecord
from tests.conftest import PATIENT, make_staff, staff_token
from tests.test_appointments import book, patient, staff_headers, world  # noqa: F401  (world is a fixture)

API = "/api/v1"


def near_slot(db, bs, minutes=30, capacity=3):
    """A slot starting `minutes` from now, today (skips the test if that would cross midnight)."""
    dt = svc.now_local() + timedelta(minutes=minutes)
    if dt.date() != svc.now_local().date() or (dt + timedelta(minutes=60)).date() != dt.date():
        pytest.skip("too close to midnight for a same-day slot")
    dt = dt.replace(second=0, microsecond=0)
    while db.scalar(select(AppointmentSlot.slot_id).where(
        AppointmentSlot.branch_service_id == bs.branch_service_id, AppointmentSlot.slot_date == dt.date(),
        AppointmentSlot.start_time == dt.time())):
        dt += timedelta(minutes=1)  # each slot in a test needs its own start time
    slot = AppointmentSlot(
        branch_service_id=bs.branch_service_id, slot_date=dt.date(), start_time=dt.time(),
        end_time=(dt + timedelta(minutes=30)).time(), capacity=capacity,
    )
    db.add(slot)
    db.commit()
    return slot


def token(branch_id=1):
    return q.make_checkin_token(branch_id)


def check_in(client, headers, branch_id=1, **extra):
    return client.post(f"{API}/me/check-in", json={"branch_token": token(branch_id), **extra}, headers=headers)


def booked_patient(client, world, n, minutes=30, bs_key="bs1"):
    h = patient(client, n)
    slot = near_slot(world["db"], world[bs_key], minutes)
    r = book(client, h, slot.slot_id)
    assert r.status_code == 201, r.text
    return h, r.json()


def nurse(client, db, branch_ids=(1,)):
    return staff_headers(client, db, "nurse@clinic.example.com", "nurse", branch_ids=branch_ids)


def reception(client, db, email="rec@clinic.example.com", branch_ids=(1,)):
    return staff_headers(client, db, email, "receptionist", branch_ids=branch_ids)


# ------------------------------------------------------------------ patient check-in


def test_patient_checks_in_and_gets_queue_numbers(client, world):
    a, appt_a = booked_patient(client, world, 1)
    b, _ = booked_patient(client, world, 2, minutes=35)
    r = check_in(client, a)
    assert r.status_code == 201, r.text
    assert r.json()["queue_number"] == 1 and r.json()["queue_status"] == "waiting" and r.json()["people_ahead"] == 0
    assert r.json()["appointment_reference"] == appt_a["appointment_reference"]
    second = check_in(client, b).json()
    assert second["queue_number"] == 2 and second["people_ahead"] == 1
    assert second["estimated_wait_minutes"] == 30 and "Estimate" in second["estimate_note"]  # FR-040
    assert world["db"].get(Appointment, appt_a["appointment_id"], populate_existing=True).status == "checked_in"


def test_queue_numbers_are_per_branch(client, world):
    a, _ = booked_patient(client, world, 1)
    c, _ = booked_patient(client, world, 3, bs_key="bs2")
    assert check_in(client, a, 1).json()["queue_number"] == 1
    assert check_in(client, c, 2).json()["queue_number"] == 1  # BR-007: numbering restarts per branch


def test_check_in_at_wrong_branch_is_refused(client, world):
    a, _ = booked_patient(client, world, 1)  # appointment at branch 1
    r = check_in(client, a, branch_id=2)
    assert r.status_code == 404 or r.status_code == 409  # no booked appointment there / wrong branch (BR-006)
    ref = client.get(f"{API}/me/appointments", headers=a).json()[0]["appointment_reference"]
    r = check_in(client, a, branch_id=2, appointment_reference=ref)
    assert r.status_code == 409 and "Test Branch" in r.json()["detail"]


def test_forged_or_malformed_branch_code_rejected(client, world):
    a, _ = booked_patient(client, world, 1)
    for bad in ("1.deadbeef", "garbage", "", "1.", "x.y"):
        assert client.post(f"{API}/me/check-in", json={"branch_token": bad}, headers=a).status_code == 400
    assert client.post(f"{API}/me/check-in", json={"branch_token": token()}).status_code == 401


def test_cannot_check_in_twice_or_when_cancelled(client, world):
    a, appt = booked_patient(client, world, 1)
    assert check_in(client, a).status_code == 201
    again = check_in(client, a, appointment_reference=appt["appointment_reference"])
    assert again.status_code == 409 and "already" in again.json()["detail"]

    b, appt_b = booked_patient(client, world, 2)
    # the slot is inside the patient cancellation cutoff, so reception cancels it
    rec = reception(client, world["db"])
    assert client.post(f"{API}/appointments/{appt_b['appointment_id']}/cancel", headers=rec).status_code == 200
    r = check_in(client, b, appointment_reference=appt_b["appointment_reference"])
    assert r.status_code == 409 and "cancelled" in r.json()["detail"]  # BR-005


def test_check_in_window_and_not_today(client, world):
    early_slot = near_slot(world["db"], world["bs1"], minutes=180)
    a = patient(client, 1)
    appt = book(client, a, early_slot.slot_id).json()
    r = check_in(client, a, appointment_reference=appt["appointment_reference"])
    assert r.status_code == 409 and "Check-in opens at" in r.json()["detail"]
    # staff may check in early (patient arrived early and is being seen)
    rec = reception(client, world["db"])
    assert client.post(f"{API}/branches/1/check-in", json={"appointment_reference": appt["appointment_reference"]}, headers=rec).status_code == 201

    b = patient(client, 2)
    tomorrow = book(client, b, client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()[0]["slot_id"]).json()
    r = check_in(client, b, appointment_reference=tomorrow["appointment_reference"])
    assert r.status_code == 409 and "not today" in r.json()["detail"]


def test_cannot_check_in_someone_elses_appointment(client, world):
    a, appt = booked_patient(client, world, 1)
    b = patient(client, 2)
    assert check_in(client, b, appointment_reference=appt["appointment_reference"]).status_code == 404


def test_no_appointment_today_and_multiple_appointments(client, world):
    nobody = patient(client, 9)
    assert check_in(client, nobody).status_code == 404
    h = patient(client, 1)
    s1, s2 = near_slot(world["db"], world["bs1"], 30), near_slot(world["db"], world["bs1"], 40)
    r1, r2 = book(client, h, s1.slot_id).json(), book(client, h, s2.slot_id).json()
    r = check_in(client, h)
    assert r.status_code == 409 and r1["appointment_reference"] in r.json()["detail"] and r2["appointment_reference"] in r.json()["detail"]
    assert check_in(client, h, appointment_reference=r2["appointment_reference"]).status_code == 201


# ------------------------------------------------------------------ staff check-in


def test_receptionist_checks_in_by_reference_and_by_membership_qr(client, world):
    db = world["db"]
    rec = reception(client, db)
    a, appt_a = booked_patient(client, world, 1)
    r = client.post(f"{API}/branches/1/check-in", json={"appointment_reference": appt_a["appointment_reference"].lower()}, headers=rec)
    assert r.status_code == 201 and r.json()["patient_name"] == "Thandi Nkosi" and r.json()["queue_number"] == 1

    reg = client.post(f"{API}/auth/register", json={**PATIENT, "email": "qr@example.com", "phone": "0829990000", "id_number": "QRID000001"}).json()
    qr_headers = {"Authorization": f"Bearer {reg['access_token']}"}
    book(client, qr_headers, near_slot(db, world["bs1"], 45).slot_id)
    r = client.post(f"{API}/branches/1/check-in", json={"qr_token": reg["membership"]["qr_token"]}, headers=rec)
    assert r.status_code == 201 and r.json()["queue_number"] == 2
    assert client.post(f"{API}/branches/1/check-in", json={"qr_token": "nope"}, headers=rec).status_code == 404
    assert client.post(f"{API}/branches/1/check-in", json={}, headers=rec).status_code == 422
    assert db.scalar(select(QueueEntry.check_in_method).where(QueueEntry.queue_number == 2)) == "membership_qr"


def test_staff_check_in_branch_scope_and_roles(client, world):
    db = world["db"]
    a, appt = booked_patient(client, world, 1)
    other = reception(client, db, "rec2@clinic.example.com", branch_ids=(2,))
    assert client.post(f"{API}/branches/1/check-in", json={"appointment_reference": appt["appointment_reference"]}, headers=other).status_code == 403  # FR-017
    # a receptionist at branch 2 checking an appointment for branch 1 into branch 2 is refused by the branch rule
    r = client.post(f"{API}/branches/2/check-in", json={"appointment_reference": appt["appointment_reference"]}, headers=other)
    assert r.status_code == 409
    n = nurse(client, db)
    assert client.post(f"{API}/branches/1/check-in", json={"appointment_reference": appt["appointment_reference"]}, headers=n).status_code == 403
    assert client.post(f"{API}/branches/1/check-in", json={"appointment_reference": appt["appointment_reference"]}).status_code == 401
    assert client.post(f"{API}/branches/1/check-in", json={"appointment_reference": "APT-NOTREAL1"}, headers=reception(client, db)).status_code == 404


def test_branch_qr_is_staff_only_and_is_a_png(client, world):
    rec = reception(client, world["db"])
    r = client.get(f"{API}/branches/1/check-in-qr.png", headers=rec)
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get(f"{API}/branches/1/check-in-qr.png").status_code == 401
    assert client.get(f"{API}/branches/2/check-in-qr.png", headers=rec).status_code == 403


# ------------------------------------------------------------------ running the queue


def test_call_next_is_first_come_first_served_and_updates_patient_view(client, world):
    db = world["db"]
    a, _ = booked_patient(client, world, 1)
    b, _ = booked_patient(client, world, 2, minutes=35)
    check_in(client, a)
    check_in(client, b)
    n = nurse(client, db)

    assert client.get(f"{API}/me/queue", headers=b).json()["people_ahead"] == 1
    called = client.post(f"{API}/branches/1/queue/call-next", headers=n)
    assert called.status_code == 200 and called.json()["queue_number"] == 1 and called.json()["queue_status"] == "called"
    assert client.get(f"{API}/me/queue", headers=a).json()["queue_status"] == "called"
    assert client.get(f"{API}/me/queue", headers=b).json()["people_ahead"] == 0  # FR-039: patient sees the change
    assert client.post(f"{API}/branches/1/queue/call-next", headers=n).json()["queue_number"] == 2
    assert client.post(f"{API}/branches/1/queue/call-next", headers=n).status_code == 404  # nobody left


def test_call_next_permissions(client, world):
    db = world["db"]
    a, _ = booked_patient(client, world, 1)
    check_in(client, a)
    assert client.post(f"{API}/branches/1/queue/call-next", headers=reception(client, db)).status_code == 403
    assert client.post(f"{API}/branches/1/queue/call-next", headers=a).status_code == 401
    other_nurse = staff_headers(client, db, "nurse2@clinic.example.com", "nurse", branch_ids=(2,))
    assert client.post(f"{API}/branches/1/queue/call-next", headers=other_nurse).status_code == 403


def test_status_transitions_and_appointment_side_effects(client, world):
    db = world["db"]
    a, appt = booked_patient(client, world, 1)
    qid = check_in(client, a).json()["queue_id"]
    n = nurse(client, db)
    rec = reception(client, db)

    def move(headers, new):
        return client.patch(f"{API}/queue/{qid}/status", json={"status": new}, headers=headers)

    assert move(n, "in_service").status_code == 409  # must be called first
    assert move(n, "completed").status_code == 422  # only via the complete-visit action
    assert move(n, "nonsense").status_code == 422
    assert move(rec, "skipped").json()["queue_status"] == "skipped"
    assert move(rec, "waiting").json()["queue_status"] == "waiting"  # skipped patient arrives and rejoins
    assert move(rec, "called").json()["queue_status"] == "called"
    assert move(rec, "in_service").status_code == 403  # only a nurse starts a service
    started = move(n, "in_service")
    assert started.status_code == 200 and started.json()["started_at"] is not None
    assert db.get(Appointment, appt["appointment_id"], populate_existing=True).status == "in_progress"
    assert move(n, "cancelled").status_code == 409  # cannot cancel once in service


def test_cancelled_queue_entry_marks_no_show(client, world):
    db = world["db"]
    a, appt = booked_patient(client, world, 1)
    qid = check_in(client, a).json()["queue_id"]
    rec = reception(client, db)
    r = client.patch(f"{API}/queue/{qid}/status", json={"status": "cancelled"}, headers=rec)
    assert r.status_code == 200
    assert db.get(Appointment, appt["appointment_id"], populate_existing=True).status == "no_show"
    assert client.patch(f"{API}/queue/{qid}/status", json={"status": "waiting"}, headers=rec).status_code == 409


def test_complete_visit_creates_visit_record(client, world):
    db = world["db"]
    a, appt = booked_patient(client, world, 1)
    qid = check_in(client, a).json()["queue_id"]
    n = nurse(client, db)
    assert client.post(f"{API}/queue/{qid}/complete", headers=n).status_code == 409  # not in service yet
    client.post(f"{API}/branches/1/queue/call-next", headers=n)
    client.patch(f"{API}/queue/{qid}/status", json={"status": "in_service"}, headers=n)
    assert client.post(f"{API}/queue/{qid}/complete", headers=reception(client, db)).status_code == 403
    r = client.post(f"{API}/queue/{qid}/complete", headers=n)
    assert r.status_code == 200 and r.json()["queue_status"] == "completed" and r.json()["completed_at"] is not None
    assert db.get(Appointment, appt["appointment_id"], populate_existing=True).status == "completed"
    assert db.scalar(select(VisitRecord.appointment_id)) == appt["appointment_id"]
    assert client.post(f"{API}/queue/{qid}/complete", headers=n).status_code == 409  # not twice
    assert check_in(client, a, appointment_reference=appt["appointment_reference"]).status_code == 409  # BR-005


def test_staff_queue_view_and_branch_scope(client, world):
    db = world["db"]
    a, _ = booked_patient(client, world, 1)
    check_in(client, a)
    n = nurse(client, db)
    rows = client.get(f"{API}/branches/1/queue", headers=n).json()
    assert len(rows) == 1 and rows[0]["patient_name"] == "Thandi Nkosi" and rows[0]["service_name"] == "Flu vaccination"
    assert client.get(f"{API}/branches/2/queue", headers=n).status_code == 403
    assert client.get(f"{API}/branches/1/queue", headers=a).status_code == 401
    assert client.get(f"{API}/branches/1/queue", params={"date": world["date"].isoformat()}, headers=n).json() == []


def test_patient_not_in_queue_gets_404(client, world):
    assert client.get(f"{API}/me/queue", headers=patient(client, 1)).status_code == 404
    assert client.get(f"{API}/me/queue").status_code == 401
