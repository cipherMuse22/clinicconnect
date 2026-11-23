from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.accounts.models import Patient
from app.modules.appointments import service as svc
from app.modules.appointments.models import AppointmentSlot
from app.modules.audit.models import AuditLog
from app.modules.branches.models import BranchHours
from app.modules.services.models import BranchService, Service
from tests.conftest import PATIENT, make_staff, staff_token

API = "/api/v1"


# ------------------------------------------------------------------ helpers


@pytest.fixture()
def world(db_session, seeded):
    """Branch 1 + 2 open every day 08:00-17:00, one 30-minute service offered at both,
    and slots (capacity 2) for branch 1 ten days from now."""
    db = db_session
    for bid in (1, 2):
        for d in range(7):
            db.add(BranchHours(branch_id=bid, day_of_week=d, open_time=__import__("datetime").time(8), close_time=__import__("datetime").time(17)))
    service = Service(service_name="Flu vaccination", estimated_duration_min=30)
    db.add(service)
    db.flush()
    bs1 = BranchService(branch_id=1, service_id=service.service_id)
    bs2 = BranchService(branch_id=2, service_id=service.service_id)
    db.add_all([bs1, bs2])
    db.flush()
    target = svc.now_local().date() + timedelta(days=10)
    created = svc.generate_slots(db, bs1, service, target, target, capacity=2)
    db.commit()
    assert created == 18  # 09 hours / 30 minutes
    return {"db": db, "service": service, "bs1": bs1, "bs2": bs2, "date": target}


def make_slot(db, bs, start, capacity=1, day=None, hours_from_now=None):
    """Insert a slot directly (outside normal opening hours if needed)."""
    from datetime import datetime, time

    if hours_from_now is not None:
        dt = svc.now_local() + timedelta(hours=hours_from_now)
        day, start = dt.date(), dt.time().replace(microsecond=0)
        end = (dt + timedelta(minutes=30)).time().replace(microsecond=0)
    else:
        day = day or svc.now_local().date() + timedelta(days=10)
        start = time.fromisoformat(start)
        end = (datetime.combine(day, start) + timedelta(minutes=30)).time()
    slot = AppointmentSlot(branch_service_id=bs.branch_service_id, slot_date=day, start_time=start, end_time=end, capacity=capacity)
    db.add(slot)
    db.commit()
    return slot


def patient(client, n=1):
    body = {**PATIENT, "email": f"p{n}@example.com", "phone": f"08211100{n:02d}", "id_number": f"ID{n:010d}"}
    r = client.post(f"{API}/auth/register", json=body)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def first_slot(world, client):
    s = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    return s[0]


def book(client, headers, slot_id):
    return client.post(f"{API}/me/appointments", json={"slot_id": slot_id}, headers=headers)


def staff_headers(client, db, email, role, branch_ids=(1,)):
    make_staff(db, email, role, branch_ids=branch_ids)
    return {"Authorization": f"Bearer {staff_token(client, email)}"}


# ------------------------------------------------------------------ availability


def test_slots_listing_is_public(client, world):
    slots = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    assert len(slots) == 18
    assert slots[0]["start_time"] == "08:00:00" and slots[0]["spots_left"] == 2 and slots[0]["available"] is True
    assert client.get(f"{API}/branches/1/services/999/slots", params={"date": world["date"].isoformat()}).status_code == 404


def test_unavailable_service_has_no_slots_and_cannot_be_booked(client, world):
    slot = first_slot(world, client)
    world["bs1"].availability_status = "unavailable"
    world["db"].commit()
    assert client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json() == []
    assert book(client, patient(client), slot["slot_id"]).status_code == 409  # FR-051


# ------------------------------------------------------------------ booking


def test_patient_books_and_availability_drops(client, world):
    h = patient(client)
    slot = first_slot(world, client)
    r = book(client, h, slot["slot_id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["appointment_reference"].startswith("APT-") and len(body["appointment_reference"]) == 12
    assert body["status"] == "booked" and body["branch_name"] == "Test Branch" and body["service_name"] == "Flu vaccination"
    assert first_slot(world, client)["spots_left"] == 1  # FR-030


def test_booking_requires_login(client, world):
    assert client.post(f"{API}/me/appointments", json={"slot_id": 1}).status_code == 401


def test_same_patient_cannot_book_same_slot_twice(client, world):
    h = patient(client)
    slot = first_slot(world, client)
    assert book(client, h, slot["slot_id"]).status_code == 201
    assert book(client, h, slot["slot_id"]).status_code == 409
    assert first_slot(world, client)["spots_left"] == 1  # the failed attempt did not use a place


def test_full_slot_cannot_be_booked_and_cancel_frees_it(client, world):
    slot = make_slot(world["db"], world["bs1"], "18:00", capacity=1)
    a, b = patient(client, 1), patient(client, 2)
    first = book(client, a, slot.slot_id)
    assert first.status_code == 201
    assert book(client, b, slot.slot_id).status_code == 409  # FR-026, BR-004
    assert client.post(f"{API}/me/appointments/{first.json()['appointment_id']}/cancel", headers=a).status_code == 200
    assert book(client, b, slot.slot_id).status_code == 201  # place was released


def test_cannot_book_a_slot_in_the_past(client, world):
    slot = make_slot(world["db"], world["bs1"], "08:00", day=svc.now_local().date() - timedelta(days=1))
    assert book(client, patient(client), slot.slot_id).status_code == 409


def test_unknown_slot_is_404(client, world):
    assert book(client, patient(client), 99999).status_code == 404


def test_patient_can_rebook_after_cancelling(client, world):
    h = patient(client)
    slot = first_slot(world, client)
    appt = book(client, h, slot["slot_id"]).json()
    client.post(f"{API}/me/appointments/{appt['appointment_id']}/cancel", headers=h)
    assert book(client, h, slot["slot_id"]).status_code == 201


# ------------------------------------------------------------------ my appointments / privacy


def test_patients_only_see_their_own_appointments(client, world):
    a, b = patient(client, 1), patient(client, 2)
    slot = first_slot(world, client)
    appt = book(client, a, slot["slot_id"]).json()
    assert len(client.get(f"{API}/me/appointments", headers=a).json()) == 1
    assert client.get(f"{API}/me/appointments", headers=b).json() == []
    aid = appt["appointment_id"]
    assert client.get(f"{API}/me/appointments/{aid}", headers=b).status_code == 404
    assert client.post(f"{API}/me/appointments/{aid}/cancel", headers=b).status_code == 404
    assert client.post(f"{API}/me/appointments/{aid}/reschedule", json={"new_slot_id": 2}, headers=b).status_code == 404
    assert client.get(f"{API}/me/appointments/{aid}", headers=a).status_code == 200


def test_upcoming_and_past_scopes(client, world):
    h = patient(client)
    slot = first_slot(world, client)
    appt = book(client, h, slot["slot_id"]).json()
    assert len(client.get(f"{API}/me/appointments", params={"scope": "upcoming"}, headers=h).json()) == 1
    assert client.get(f"{API}/me/appointments", params={"scope": "past"}, headers=h).json() == []
    client.post(f"{API}/me/appointments/{appt['appointment_id']}/cancel", headers=h)
    assert client.get(f"{API}/me/appointments", params={"scope": "upcoming"}, headers=h).json() == []
    past = client.get(f"{API}/me/appointments", params={"scope": "past"}, headers=h).json()
    assert past[0]["status"] == "cancelled" and past[0]["cancellation_reason"] is None
    assert client.get(f"{API}/me/appointments", params={"scope": "bogus"}, headers=h).status_code == 422


# ------------------------------------------------------------------ cancel rules


def test_cancel_records_reason_and_cannot_repeat(client, world):
    h = patient(client)
    appt = book(client, h, first_slot(world, client)["slot_id"]).json()
    r = client.post(f"{API}/me/appointments/{appt['appointment_id']}/cancel", json={"reason": "Feeling better"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancellation_reason"] == "Feeling better"
    assert r.json()["cancelled_at"] is not None
    assert client.post(f"{API}/me/appointments/{appt['appointment_id']}/cancel", headers=h).status_code == 409
    assert first_slot(world, client)["spots_left"] == 2


def test_patient_cannot_cancel_inside_cutoff_but_staff_can(client, world):
    slot = make_slot(world["db"], world["bs1"], "", capacity=1, hours_from_now=1)  # starts in 1 hour
    h = patient(client)
    appt = book(client, h, slot.slot_id)
    assert appt.status_code == 201, appt.text
    aid = appt.json()["appointment_id"]
    r = client.post(f"{API}/me/appointments/{aid}/cancel", headers=h)
    assert r.status_code == 409 and "call the branch" in r.json()["detail"]
    rec = staff_headers(client, world["db"], "rec@clinic.example.com", "receptionist")
    assert client.post(f"{API}/appointments/{aid}/cancel", headers=rec).status_code == 200


# ------------------------------------------------------------------ reschedule


def test_reschedule_moves_booking_and_adjusts_counts(client, world):
    h = patient(client)
    slots = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    appt = book(client, h, slots[0]["slot_id"]).json()
    r = client.post(f"{API}/me/appointments/{appt['appointment_id']}/reschedule", json={"new_slot_id": slots[1]["slot_id"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["slot_id"] == slots[1]["slot_id"] and r.json()["start_time"] == "08:30:00"
    assert r.json()["appointment_reference"] == appt["appointment_reference"]  # same booking, same reference
    after = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    assert after[0]["spots_left"] == 2 and after[1]["spots_left"] == 1


def test_reschedule_to_full_slot_leaves_original_intact(client, world):
    full = make_slot(world["db"], world["bs1"], "18:00", capacity=1)
    a, b = patient(client, 1), patient(client, 2)
    assert book(client, a, full.slot_id).status_code == 201
    slot = first_slot(world, client)
    mine = book(client, b, slot["slot_id"]).json()
    r = client.post(f"{API}/me/appointments/{mine['appointment_id']}/reschedule", json={"new_slot_id": full.slot_id}, headers=b)
    assert r.status_code == 409
    still = client.get(f"{API}/me/appointments/{mine['appointment_id']}", headers=b).json()
    assert still["slot_id"] == slot["slot_id"] and still["status"] == "booked"
    assert first_slot(world, client)["spots_left"] == 1  # original place not lost


def test_reschedule_must_stay_at_same_branch_and_service(client, world):
    other_branch_slot = make_slot(world["db"], world["bs2"], "10:00", capacity=2)
    h = patient(client)
    appt = book(client, h, first_slot(world, client)["slot_id"]).json()
    r = client.post(f"{API}/me/appointments/{appt['appointment_id']}/reschedule", json={"new_slot_id": other_branch_slot.slot_id}, headers=h)
    assert r.status_code == 422
    same = client.post(f"{API}/me/appointments/{appt['appointment_id']}/reschedule", json={"new_slot_id": appt["slot_id"]}, headers=h)
    assert same.status_code == 422


# ------------------------------------------------------------------ staff


def test_staff_search_book_for_patient_and_view_schedule(client, world):
    db = world["db"]
    patient(client, 7)
    pid = db.scalar(select(Patient.patient_id).where(Patient.email == "p7@example.com"))
    rec = staff_headers(client, db, "rec@clinic.example.com", "receptionist", branch_ids=(1,))

    found = client.get(f"{API}/patients/search", params={"q": "Nkosi"}, headers=rec).json()
    assert len(found) == 1 and found[0]["patient_id"] == pid and found[0]["membership_number"].startswith("CC")
    assert client.get(f"{API}/patients/search", params={"q": "ab"}, headers=rec).status_code == 422
    assert client.get(f"{API}/patients/search", params={"q": "%%%"}, headers=rec).json() == []  # no wildcard abuse

    slot = first_slot(world, client)
    r = client.post(f"{API}/appointments", json={"patient_id": pid, "slot_id": slot["slot_id"]}, headers=rec)
    assert r.status_code == 201, r.text
    assert r.json()["patient_name"] == "Thandi Nkosi"

    sched = client.get(f"{API}/branches/1/appointments", params={"date": world["date"].isoformat()}, headers=rec).json()
    assert len(sched) == 1 and sched[0]["patient_phone"] == "0821110007" and sched[0]["appointment_reference"].startswith("APT-")
    assert "create_for_patient" in "".join(db.scalars(select(AuditLog.action)).all())


def test_staff_branch_scope_and_role_checks(client, world):
    db = world["db"]
    rec_other = staff_headers(client, db, "rec2@clinic.example.com", "receptionist", branch_ids=(2,))
    nurse = staff_headers(client, db, "nurse@clinic.example.com", "nurse", branch_ids=(1,))
    h = patient(client)
    pid = db.scalar(select(Patient.patient_id))
    slot = first_slot(world, client)

    # receptionist of branch 2 cannot book into / view branch 1 (FR-017)
    assert client.post(f"{API}/appointments", json={"patient_id": pid, "slot_id": slot["slot_id"]}, headers=rec_other).status_code == 403
    assert client.get(f"{API}/branches/1/appointments", headers=rec_other).status_code == 403
    # nurse may view the schedule but not book or search patients
    assert client.get(f"{API}/branches/1/appointments", headers=nurse).status_code == 200
    assert client.post(f"{API}/appointments", json={"patient_id": pid, "slot_id": slot["slot_id"]}, headers=nurse).status_code == 403
    assert client.get(f"{API}/patients/search", params={"q": "Nkosi"}, headers=nurse).status_code == 403
    # patients cannot use staff routes at all
    assert client.get(f"{API}/branches/1/appointments", headers=h).status_code == 401
    assert client.get(f"{API}/patients/search", params={"q": "Nkosi"}, headers=h).status_code == 401


def test_staff_reschedule(client, world):
    db = world["db"]
    rec = staff_headers(client, db, "rec@clinic.example.com", "receptionist")
    h = patient(client)
    slots = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": world["date"].isoformat()}).json()
    appt = book(client, h, slots[0]["slot_id"]).json()
    r = client.post(f"{API}/appointments/{appt['appointment_id']}/reschedule", json={"new_slot_id": slots[2]["slot_id"]}, headers=rec)
    assert r.status_code == 200 and r.json()["start_time"] == "09:00:00"


# ------------------------------------------------------------------ slot generation


def test_manager_generates_slots_for_own_branch_only(client, world):
    db = world["db"]
    mgr = staff_headers(client, db, "mgr@clinic.example.com", "clinic_manager", branch_ids=(1,))
    d = (world["date"] + timedelta(days=1)).isoformat()
    body = {"service_id": world["service"].service_id, "from_date": d, "to_date": d, "capacity": 3}
    r = client.post(f"{API}/branches/1/slots/generate", json=body, headers=mgr)
    assert r.status_code == 200 and r.json() == {"created": 18}
    assert client.post(f"{API}/branches/1/slots/generate", json=body, headers=mgr).json() == {"created": 0}  # safe to repeat
    assert client.post(f"{API}/branches/2/slots/generate", json=body, headers=mgr).status_code == 403
    slots = client.get(f"{API}/branches/1/services/{world['service'].service_id}/slots", params={"date": d}).json()
    assert slots[0]["capacity"] == 3


def test_slot_generation_validation_and_closed_days(client, world):
    db = world["db"]
    adm = staff_headers(client, db, "admin@clinic.example.com", "system_admin")
    sid = world["service"].service_id
    today = svc.now_local().date()
    base = {"service_id": sid, "capacity": 2}
    assert client.post(f"{API}/branches/1/slots/generate", json={**base, "from_date": (today - timedelta(days=1)).isoformat(), "to_date": today.isoformat()}, headers=adm).status_code == 422
    assert client.post(f"{API}/branches/1/slots/generate", json={**base, "from_date": today.isoformat(), "to_date": (today + timedelta(days=40)).isoformat()}, headers=adm).status_code == 422
    assert client.post(f"{API}/branches/1/slots/generate", json={**base, "from_date": (today + timedelta(days=5)).isoformat(), "to_date": (today + timedelta(days=4)).isoformat()}, headers=adm).status_code == 422
    # a day with no opening hours produces nothing
    d = today + timedelta(days=20)
    db.query(BranchHours).filter_by(branch_id=1, day_of_week=d.weekday()).delete()
    db.commit()
    r = client.post(f"{API}/branches/1/slots/generate", json={**base, "from_date": d.isoformat(), "to_date": d.isoformat()}, headers=adm)
    assert r.json() == {"created": 0}
    assert client.post(f"{API}/branches/1/slots/generate", json={"service_id": 999, "from_date": d.isoformat(), "to_date": d.isoformat()}, headers=adm).status_code == 404
