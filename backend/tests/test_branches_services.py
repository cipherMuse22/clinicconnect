from sqlalchemy import select

from app.modules.audit.models import AuditLog
from tests.conftest import make_staff, staff_token

API = "/api/v1"
WEEK = [{"day_of_week": d, "open_time": "08:00", "close_time": "17:00"} for d in range(5)]


def auth(client, email):
    return {"Authorization": f"Bearer {staff_token(client, email)}"}


def admin_headers(client, db):
    make_staff(db, "admin@clinic.example.com", "system_admin")
    return auth(client, "admin@clinic.example.com")


def manager_headers(client, db, branch_ids=(1,), email="mgr@clinic.example.com"):
    make_staff(db, email, "clinic_manager", branch_ids=branch_ids)
    return auth(client, email)


# ---------- public browsing ----------


def test_public_can_list_branches_and_hours(client, db_session, seeded):
    h = admin_headers(client, db_session)
    client.put(f"{API}/branches/1/hours", json=WEEK, headers=h)
    r = client.get(f"{API}/branches")  # no login needed
    assert r.status_code == 200
    names = [b["branch_name"] for b in r.json()]
    assert names == ["Other Branch", "Test Branch"]
    one = client.get(f"{API}/branches/1").json()
    assert len(one["hours"]) == 5 and one["hours"][0]["open_time"] == "08:00:00"


def test_inactive_branch_hidden_from_public(client, db_session, seeded):
    h = admin_headers(client, db_session)
    assert client.patch(f"{API}/branches/2", json={"status": "inactive"}, headers=h).status_code == 200
    assert [b["branch_id"] for b in client.get(f"{API}/branches").json()] == [1]
    assert client.get(f"{API}/branches/2").status_code == 404
    assert client.get(f"{API}/branches/2/services").status_code == 404


# ---------- branch management ----------


def test_only_admin_creates_and_updates_branch(client, db_session, seeded):
    body = {"branch_name": "New Branch", "address": "1 Road", "phone": "0110001111"}
    assert client.post(f"{API}/branches", json=body).status_code == 401
    mgr = manager_headers(client, db_session)
    assert client.post(f"{API}/branches", json=body, headers=mgr).status_code == 403
    assert client.patch(f"{API}/branches/1", json={"phone": "1"}, headers=mgr).status_code == 403
    adm = admin_headers(client, db_session)
    r = client.post(f"{API}/branches", json=body, headers=adm)
    assert r.status_code == 201 and r.json()["hours"] == []
    assert client.patch(f"{API}/branches/1", json={"status": "bogus"}, headers=adm).status_code == 422


def test_manager_sets_hours_only_for_own_branch(client, db_session, seeded):
    mgr = manager_headers(client, db_session, branch_ids=(1,))
    assert client.put(f"{API}/branches/1/hours", json=WEEK, headers=mgr).status_code == 200
    r = client.put(f"{API}/branches/2/hours", json=WEEK, headers=mgr)
    assert r.status_code == 403  # FR-017
    # replacing hours works repeatedly (no unique-constraint clash)
    again = client.put(f"{API}/branches/1/hours", json=WEEK[:2], headers=mgr)
    assert again.status_code == 200 and len(again.json()["hours"]) == 2


def test_admin_can_set_hours_for_any_branch(client, db_session, seeded):
    adm = admin_headers(client, db_session)
    assert client.put(f"{API}/branches/2/hours", json=WEEK, headers=adm).status_code == 200


def test_hours_validation(client, db_session, seeded):
    adm = admin_headers(client, db_session)
    bad_order = [{"day_of_week": 0, "open_time": "17:00", "close_time": "08:00"}]
    dup_day = [WEEK[0], WEEK[0]]
    bad_day = [{"day_of_week": 7, "open_time": "08:00", "close_time": "09:00"}]
    for payload in (bad_order, dup_day, bad_day):
        assert client.put(f"{API}/branches/1/hours", json=payload, headers=adm).status_code == 422


def test_receptionist_cannot_set_hours(client, db_session, seeded):
    make_staff(db_session, "rec@clinic.example.com", "receptionist", branch_ids=(1,))
    h = auth(client, "rec@clinic.example.com")
    assert client.put(f"{API}/branches/1/hours", json=WEEK, headers=h).status_code == 403


# ---------- services ----------


def test_service_catalogue_admin_only_and_unique(client, db_session, seeded):
    body = {"service_name": "Flu vaccination", "description": "Seasonal", "estimated_duration_min": 15}
    assert client.post(f"{API}/services", json=body).status_code == 401
    mgr = manager_headers(client, db_session)
    assert client.post(f"{API}/services", json=body, headers=mgr).status_code == 403
    adm = admin_headers(client, db_session)
    assert client.post(f"{API}/services", json=body, headers=adm).status_code == 201
    assert client.post(f"{API}/services", json=body, headers=adm).status_code == 409
    assert client.post(f"{API}/services", json={**body, "service_name": "X ray", "estimated_duration_min": 0}, headers=adm).status_code == 422
    assert [s["service_name"] for s in client.get(f"{API}/services").json()] == ["Flu vaccination"]


def test_inactive_service_hidden_everywhere(client, db_session, seeded):
    adm = admin_headers(client, db_session)
    sid = client.post(f"{API}/services", json={"service_name": "Wellness check", "estimated_duration_min": 30}, headers=adm).json()["service_id"]
    client.put(f"{API}/branches/1/services/{sid}", json={}, headers=adm)
    assert len(client.get(f"{API}/branches/1/services").json()) == 1
    client.patch(f"{API}/services/{sid}", json={"status": "inactive"}, headers=adm)
    assert client.get(f"{API}/services").json() == []
    assert client.get(f"{API}/branches/1/services").json() == []


def test_branch_service_configuration_and_availability(client, db_session, seeded):
    adm = admin_headers(client, db_session)
    sid = client.post(f"{API}/services", json={"service_name": "Flu vaccination", "estimated_duration_min": 15}, headers=adm).json()["service_id"]
    mgr = manager_headers(client, db_session, branch_ids=(1,))

    # manager offers the service at their own branch; shows as available (FR-020, FR-021)
    r = client.put(f"{API}/branches/1/services/{sid}", json={}, headers=mgr)
    assert r.status_code == 200 and r.json()["available"] is True
    # ... and marks it unavailable (FR-050)
    r = client.put(f"{API}/branches/1/services/{sid}", json={"availability_status": "unavailable"}, headers=mgr)
    assert r.json()["available"] is False
    listed = client.get(f"{API}/branches/1/services").json()
    assert listed[0]["availability_status"] == "unavailable" and listed[0]["available"] is False

    # not their branch
    assert client.put(f"{API}/branches/2/services/{sid}", json={}, headers=mgr).status_code == 403
    # unknown ids
    assert client.put(f"{API}/branches/1/services/999", json={}, headers=mgr).status_code == 404
    assert client.put(f"{API}/branches/99/services/{sid}", json={}, headers=adm).status_code == 404
    # bad status value
    assert client.put(f"{API}/branches/1/services/{sid}", json={"availability_status": "maybe"}, headers=mgr).status_code == 422

    # remove
    assert client.delete(f"{API}/branches/1/services/{sid}", headers=mgr).status_code == 204
    assert client.delete(f"{API}/branches/1/services/{sid}", headers=mgr).status_code == 404
    assert client.get(f"{API}/branches/1/services").json() == []


def test_changes_are_audited(client, db_session, seeded):
    adm = admin_headers(client, db_session)
    client.post(f"{API}/branches", json={"branch_name": "Audit Branch"}, headers=adm)
    client.put(f"{API}/branches/1/hours", json=WEEK, headers=adm)
    sid = client.post(f"{API}/services", json={"service_name": "Audit Service", "estimated_duration_min": 10}, headers=adm).json()["service_id"]
    client.put(f"{API}/branches/1/services/{sid}", json={}, headers=adm)
    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert {"branch.create", "branch.hours.set", "service.create", "branch_service.set"} <= actions
