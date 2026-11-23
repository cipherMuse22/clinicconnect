from app.modules.audit.models import AuditLog
from tests.conftest import make_staff, staff_token

API = "/api/v1"


def admin_h(client, db):
    make_staff(db, "boss@clinic.example.com", "system_admin")
    return {"Authorization": f"Bearer {staff_token(client, 'boss@clinic.example.com')}"}


def test_only_admin_can_manage_staff(client, seeded, db_session):
    make_staff(db_session, "nurse@clinic.example.com", "nurse", branch_ids=[1])
    h = {"Authorization": f"Bearer {staff_token(client, 'nurse@clinic.example.com')}"}
    assert client.get(f"{API}/admin/staff", headers=h).status_code == 403
    assert client.patch(f"{API}/admin/staff/1", json={"first_name": "X"}, headers=h).status_code == 403
    assert client.post(f"{API}/admin/staff/1/reset-password", json={"new_password": "NewPass1234"}, headers=h).status_code == 403


def test_list_and_update_staff(client, seeded, db_session):
    h = admin_h(client, db_session)
    nurse = make_staff(db_session, "nurse@clinic.example.com", "nurse", branch_ids=[1])
    rows = client.get(f"{API}/admin/staff", headers=h).json()
    assert {r["email"] for r in rows} == {"boss@clinic.example.com", "nurse@clinic.example.com"}

    r = client.patch(f"{API}/admin/staff/{nurse.staff_id}", headers=h,
                     json={"first_name": "Nomsa", "roles": ["nurse", "receptionist"], "branch_ids": [1, 2]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["first_name"] == "Nomsa"
    assert sorted(body["role_names"]) == ["nurse", "receptionist"]
    assert sorted(body["branch_ids"]) == [1, 2]
    assert db_session.query(AuditLog).filter_by(action="staff.update").count() == 1

    assert client.patch(f"{API}/admin/staff/{nurse.staff_id}", headers=h, json={"roles": ["wizard"]}).status_code == 422
    assert client.patch(f"{API}/admin/staff/{nurse.staff_id}", headers=h, json={"branch_ids": [99]}).status_code == 422
    assert client.patch(f"{API}/admin/staff/9999", headers=h, json={"first_name": "X"}).status_code == 404


def test_deactivated_staff_cannot_sign_in(client, seeded, db_session):
    h = admin_h(client, db_session)
    nurse = make_staff(db_session, "nurse@clinic.example.com", "nurse")
    assert client.patch(f"{API}/admin/staff/{nurse.staff_id}", headers=h, json={"account_status": "inactive"}).status_code == 200
    r = client.post(f"{API}/auth/staff/login", json={"email": "nurse@clinic.example.com", "password": "StaffPass123!"})
    assert r.status_code == 401
    client.patch(f"{API}/admin/staff/{nurse.staff_id}", headers=h, json={"account_status": "active"})
    staff_token(client, "nurse@clinic.example.com")


def test_cannot_lock_everyone_out(client, seeded, db_session):
    h = admin_h(client, db_session)
    me = client.get(f"{API}/auth/staff/me", headers=h).json()["staff_id"]
    assert client.patch(f"{API}/admin/staff/{me}", headers=h, json={"account_status": "inactive"}).status_code == 409
    assert client.patch(f"{API}/admin/staff/{me}", headers=h, json={"roles": ["nurse"]}).status_code == 409
    # with a second admin the first may step down
    other = make_staff(db_session, "boss2@clinic.example.com", "system_admin")
    assert client.patch(f"{API}/admin/staff/{me}", headers=h, json={"roles": ["nurse"]}).status_code == 200
    assert other.staff_id != me


def test_admin_password_reset(client, seeded, db_session):
    h = admin_h(client, db_session)
    nurse = make_staff(db_session, "nurse@clinic.example.com", "nurse")
    assert client.post(f"{API}/admin/staff/{nurse.staff_id}/reset-password", headers=h, json={"new_password": "short"}).status_code == 422
    assert client.post(f"{API}/admin/staff/{nurse.staff_id}/reset-password", headers=h, json={"new_password": "BrandNewPass99"}).status_code == 204
    assert client.post(f"{API}/auth/staff/login", json={"email": "nurse@clinic.example.com", "password": "StaffPass123!"}).status_code == 401
    assert client.post(f"{API}/auth/staff/login", json={"email": "nurse@clinic.example.com", "password": "BrandNewPass99"}).status_code == 200
    log = db_session.query(AuditLog).filter_by(action="staff.password_reset").one()
    assert "BrandNewPass99" not in str(log.details)


def test_admin_sees_inactive_branches_and_services(client, seeded, db_session):
    h = admin_h(client, db_session)
    assert client.patch(f"{API}/branches/2", headers=h, json={"status": "inactive"}).status_code == 200
    assert [b["branch_id"] for b in client.get(f"{API}/branches").json()] == [1]
    all_branches = client.get(f"{API}/admin/branches", headers=h).json()
    assert {b["branch_id"] for b in all_branches} == {1, 2}
    svc = client.post(f"{API}/services", headers=h, json={"service_name": "Wound care", "estimated_duration_min": 20}).json()
    client.patch(f"{API}/services/{svc['service_id']}", headers=h, json={"status": "inactive"})
    assert client.get(f"{API}/services").json() == []
    assert len(client.get(f"{API}/admin/services", headers=h).json()) == 1
    make_staff(db_session, "nurse@clinic.example.com", "nurse")
    nh = {"Authorization": f"Bearer {staff_token(client, 'nurse@clinic.example.com')}"}
    assert client.get(f"{API}/admin/branches", headers=nh).status_code == 403
