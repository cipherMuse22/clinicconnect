from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.modules.accounts.models import Patient, Staff
from app.modules.appointments import service as svc
from app.modules.appointments.models import Appointment
from app.modules.audit.models import AuditLog
from app.modules.queue.models import QueueEntry
from tests.conftest import make_staff, staff_token
from tests.test_appointments import make_slot, patient, world  # noqa: F401

API = "/api/v1"


def hdr(client, db, email, role, branch_ids=(1,)):
    if not db.scalar(select(Staff.staff_id).where(Staff.email == email)):
        make_staff(db, email, role, branch_ids=branch_ids)
    return {"Authorization": f"Bearer {staff_token(client, email)}"}


def add_appt(db, n, slot, status):
    pid = db.scalar(select(Patient.patient_id).where(Patient.email == f"p{n}@example.com"))
    a = Appointment(appointment_reference=f"APT-REPORT{n}{status[:2].upper()}", patient_id=pid, slot_id=slot.slot_id, status=status)
    db.add(a)
    db.commit()
    return a


def report_data(client, world):
    """Five appointments: branch 1 -> completed, completed, cancelled, booked ; branch 2 -> no_show."""
    db = world["db"]
    for n in range(1, 6):
        patient(client, n)
    # evening times: the world fixture already filled 08:00-17:00 at branch 1
    s1 = [make_slot(db, world["bs1"], t, capacity=5) for t in ("18:00", "18:30", "19:00", "19:30")]
    s2 = make_slot(db, world["bs2"], "18:00", capacity=5)
    appts = [
        add_appt(db, 1, s1[0], "completed"), add_appt(db, 2, s1[1], "completed"),
        add_appt(db, 3, s1[2], "cancelled"), add_appt(db, 4, s1[3], "booked"), add_appt(db, 5, s2, "no_show"),
    ]
    return appts


# ------------------------------------------------------------------ appointment report


def test_appointment_report_counts_and_rates(client, world):
    report_data(client, world)
    db = world["db"]
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    d = world["date"].isoformat()
    r = client.get(f"{API}/reports/appointments", params={"from": d, "to": d}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"] == {"total": 5, "completed": 2, "cancelled": 1, "no_show": 1, "pending": 1}  # FR-052, FR-053
    assert body["completion_rate"] == 0.4 and body["cancellation_rate"] == 0.2
    assert body["by_day"][0]["date"] == d and body["by_day"][0]["total"] == 5
    by_branch = {b["name"]: b for b in body["by_branch"]}
    assert by_branch["Test Branch"]["total"] == 4 and by_branch["Other Branch"]["no_show"] == 1
    assert body["by_service"][0]["name"] == "Flu vaccination" and body["by_service"][0]["total"] == 5
    # a range that excludes the appointments is all zeros
    other = (world["date"] + timedelta(days=3)).isoformat()
    empty = client.get(f"{API}/reports/appointments", params={"from": other, "to": other}, headers=admin).json()
    assert empty["totals"]["total"] == 0 and empty["completion_rate"] == 0.0 and empty["by_day"] == []


def test_manager_report_limited_to_own_branches(client, world):
    report_data(client, world)
    db = world["db"]
    mgr = hdr(client, db, "mgr@clinic.example.com", "clinic_manager", (1,))
    d = world["date"].isoformat()
    own = client.get(f"{API}/reports/appointments", params={"from": d, "to": d}, headers=mgr).json()
    assert own["branch_ids"] == [1] and own["totals"]["total"] == 4  # branch 2's no-show is not included (FR-017)
    assert client.get(f"{API}/reports/appointments", params={"branch_id": 2, "from": d, "to": d}, headers=mgr).status_code == 403
    assert client.get(f"{API}/reports/appointments", params={"branch_id": 99}, headers=mgr).status_code == 404
    assert client.get(f"{API}/reports/appointments", params={"branch_id": 1, "from": d, "to": d}, headers=mgr).json()["totals"]["total"] == 4


def test_report_access_and_validation(client, world):
    db = world["db"]
    rec = hdr(client, db, "rec@clinic.example.com", "receptionist")
    nurse = hdr(client, db, "nurse@clinic.example.com", "nurse")
    for path in ("appointments", "queue", "branch-performance", "system-summary"):
        assert client.get(f"{API}/reports/{path}").status_code == 401
        assert client.get(f"{API}/reports/{path}", headers=rec).status_code == 403
        assert client.get(f"{API}/reports/{path}", headers=nurse).status_code == 403
    mgr = hdr(client, db, "mgr@clinic.example.com", "clinic_manager")
    assert client.get(f"{API}/reports/system-summary", headers=mgr).status_code == 403  # admin only (FR-056)
    assert client.get(f"{API}/reports/appointments", params={"from": "2026-02-01", "to": "2026-01-01"}, headers=mgr).status_code == 422
    assert client.get(f"{API}/reports/appointments", params={"from": "2024-01-01", "to": "2026-01-01"}, headers=mgr).status_code == 422
    assert client.get(f"{API}/reports/appointments", headers=mgr).status_code == 200  # default: last 30 days
    assert client.get(f"{API}/reports/appointments", params={"from": "garbage"}, headers=mgr).status_code == 422


# ------------------------------------------------------------------ queue report


def test_queue_report_averages(client, world):
    appts = report_data(client, world)
    db = world["db"]
    today = svc.now_local().date()
    t0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    rows = [
        # waited 10 minutes, then 20 minutes of service, completed
        QueueEntry(appointment_id=appts[0].appointment_id, branch_id=1, queue_date=today, queue_number=1, queue_status="completed",
                   check_in_method="reference", check_in_time=t0, called_at=t0 + timedelta(minutes=10),
                   started_at=t0 + timedelta(minutes=12), completed_at=t0 + timedelta(minutes=32)),
        # waited 20 minutes, 10 minutes of service, completed
        QueueEntry(appointment_id=appts[1].appointment_id, branch_id=1, queue_date=today, queue_number=2, queue_status="completed",
                   check_in_method="reference", check_in_time=t0, called_at=t0 + timedelta(minutes=20),
                   started_at=t0 + timedelta(minutes=21), completed_at=t0 + timedelta(minutes=31)),
        # still waiting
        QueueEntry(appointment_id=appts[3].appointment_id, branch_id=1, queue_date=today, queue_number=3, queue_status="waiting",
                   check_in_method="reference", check_in_time=t0),
    ]
    db.add_all(rows)
    db.commit()
    mgr = hdr(client, db, "mgr@clinic.example.com", "clinic_manager", (1,))
    r = client.get(f"{API}/reports/queue", params={"from": today.isoformat(), "to": today.isoformat()}, headers=mgr).json()  # FR-054
    assert r["checked_in"] == 3 and r["by_status"] == {"completed": 2, "waiting": 1}
    assert r["avg_wait_minutes"] == 15.0 and r["avg_service_minutes"] == 15.0
    assert r["by_day"] == [{"date": today.isoformat(), "checked_in": 3, "completed": 2, "avg_wait_minutes": 15.0}]
    empty = client.get(f"{API}/reports/queue", params={"from": (today - timedelta(days=5)).isoformat(), "to": (today - timedelta(days=4)).isoformat()}, headers=mgr).json()
    assert empty["checked_in"] == 0 and empty["avg_wait_minutes"] is None


# ------------------------------------------------------------------ branch performance and system summary


def test_branch_performance_compares_branches(client, world):
    report_data(client, world)
    db = world["db"]
    d = world["date"].isoformat()
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    rows = client.get(f"{API}/reports/branch-performance", params={"from": d, "to": d}, headers=admin).json()  # FR-055
    assert [r["branch_name"] for r in rows] == ["Other Branch", "Test Branch"]
    other, test = rows
    assert test["appointments"]["total"] == 4 and test["completion_rate"] == 0.5 and test["cancellation_rate"] == 0.25
    assert other["no_show_rate"] == 1.0 and other["avg_wait_minutes"] is None
    mgr = hdr(client, db, "mgr@clinic.example.com", "clinic_manager", (1,))
    only_own = client.get(f"{API}/reports/branch-performance", params={"from": d, "to": d}, headers=mgr).json()
    assert [r["branch_name"] for r in only_own] == ["Test Branch"]


def test_system_summary(client, world):
    report_data(client, world)
    db = world["db"]
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    s = client.get(f"{API}/reports/system-summary", headers=admin).json()  # FR-056
    assert s["patients"] == 5 and s["active_staff"] == 1 and s["active_branches"] == 2 and s["active_services"] == 1
    assert s["appointments_this_month"] >= 0 and s["appointments_today"] >= 0
    assert s["queue_check_ins_today"] == 0 and s["low_stock_items"] == 0


def test_reports_contain_no_patient_details(client, world):
    report_data(client, world)
    db = world["db"]
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    d = world["date"].isoformat()
    text = "".join(client.get(f"{API}/reports/{p}", params={"from": d, "to": d}, headers=admin).text for p in ("appointments", "queue", "branch-performance"))
    assert "Thandi" not in text and "Nkosi" not in text and "@example.com" not in text


# ------------------------------------------------------------------ audit viewer


def test_audit_viewer_is_admin_only_and_filterable(client, world):
    db = world["db"]
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    mgr = hdr(client, db, "mgr@clinic.example.com", "clinic_manager", (1,))
    assert client.get(f"{API}/admin/audit-logs").status_code == 401
    assert client.get(f"{API}/admin/audit-logs", headers=mgr).status_code == 403

    client.post(f"{API}/branches", json={"branch_name": "Audit Branch One"}, headers=admin)
    client.put(f"{API}/branches/1/hours", json=[{"day_of_week": 0, "open_time": "08:00", "close_time": "12:00"}], headers=mgr)
    client.post(f"{API}/services", json={"service_name": "Audit Service", "estimated_duration_min": 10}, headers=admin)

    page = client.get(f"{API}/admin/audit-logs", headers=admin).json()
    assert page["total"] >= 3 and page["items"][0]["created_at"] >= page["items"][-1]["created_at"]
    first = next(i for i in page["items"] if i["action"] == "branch.create")
    assert first["actor_email"] == "admin@clinic.example.com" and first["details"] == {"branch_name": "Audit Branch One"}
    assert first["entity_type"] == "branch"

    prefixed = client.get(f"{API}/admin/audit-logs", params={"action": "branch."}, headers=admin).json()
    assert {i["action"] for i in prefixed["items"]} == {"branch.create", "branch.hours.set"}
    assert client.get(f"{API}/admin/audit-logs", params={"action": "service.create"}, headers=admin).json()["total"] == 1
    mgr_id = db.scalar(select(AuditLog.actor_staff_id).where(AuditLog.action == "branch.hours.set"))
    by_actor = client.get(f"{API}/admin/audit-logs", params={"actor_staff_id": mgr_id}, headers=admin).json()
    assert by_actor["total"] == 1 and by_actor["items"][0]["actor_email"] == "mgr@clinic.example.com"
    assert client.get(f"{API}/admin/audit-logs", params={"entity_type": "service"}, headers=admin).json()["total"] == 1
    assert client.get(f"{API}/admin/audit-logs", params={"action": "%"}, headers=admin).json()["total"] == 0  # no wildcard abuse


def test_audit_viewer_paging_and_dates(client, world):
    db = world["db"]
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    for i in range(5):
        client.post(f"{API}/branches", json={"branch_name": f"Paged Branch {i}"}, headers=admin)
    p1 = client.get(f"{API}/admin/audit-logs", params={"action": "branch.create", "limit": 2}, headers=admin).json()
    p2 = client.get(f"{API}/admin/audit-logs", params={"action": "branch.create", "limit": 2, "offset": 2}, headers=admin).json()
    assert p1["total"] == 5 and len(p1["items"]) == 2 and len(p2["items"]) == 2
    assert not {i["audit_id"] for i in p1["items"]} & {i["audit_id"] for i in p2["items"]}
    assert client.get(f"{API}/admin/audit-logs", params={"limit": 500}, headers=admin).status_code == 422

    today = svc.now_local().date()
    assert client.get(f"{API}/admin/audit-logs", params={"from": today.isoformat(), "to": today.isoformat(), "action": "branch.create"}, headers=admin).json()["total"] == 5
    past = (today - timedelta(days=3)).isoformat()
    assert client.get(f"{API}/admin/audit-logs", params={"from": past, "to": past}, headers=admin).json()["total"] == 0
