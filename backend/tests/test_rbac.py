from sqlalchemy import select

from app.modules.audit.models import AuditLog
from tests.conftest import PATIENT, make_staff, staff_token

API = "/api/v1"
NEW_STAFF = {
    "first_name": "Nomsa",
    "last_name": "Dlamini",
    "email": "nomsa@clinic.example.com",
    "password": "NursePass123!",
    "roles": ["nurse"],
    "branch_ids": [1],
}


def test_admin_endpoint_requires_login(client, seeded):
    assert client.post(f"{API}/admin/staff", json=NEW_STAFF).status_code == 401


def test_patient_token_cannot_use_staff_endpoints(client, seeded):
    token = client.post(f"{API}/auth/register", json=PATIENT).json()["access_token"]
    r = client.post(f"{API}/admin/staff", json=NEW_STAFF, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_non_admin_staff_forbidden(client, db_session, seeded):
    make_staff(db_session, "recep@clinic.example.com", "receptionist")
    token = staff_token(client, "recep@clinic.example.com")
    r = client.post(f"{API}/admin/staff", json=NEW_STAFF, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_creates_staff_and_audit_row_written(client, db_session, seeded):
    make_staff(db_session, "admin@clinic.example.com", "system_admin")
    token = staff_token(client, "admin@clinic.example.com")
    r = client.post(f"{API}/admin/staff", json=NEW_STAFF, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    assert r.json()["role_names"] == ["nurse"]
    assert "password" not in r.text

    log = db_session.scalar(select(AuditLog).where(AuditLog.action == "staff.create"))
    assert log is not None and log.entity_id == r.json()["staff_id"]
    assert "NursePass123" not in (log.details or "")

    # the new nurse can log in but cannot create staff
    nurse = staff_token(client, "nomsa@clinic.example.com", "NursePass123!")
    r2 = client.post(f"{API}/admin/staff", json=NEW_STAFF, headers={"Authorization": f"Bearer {nurse}"})
    assert r2.status_code == 403


def test_admin_rejects_unknown_role_and_duplicate_email(client, db_session, seeded):
    make_staff(db_session, "admin@clinic.example.com", "system_admin")
    h = {"Authorization": f"Bearer {staff_token(client, 'admin@clinic.example.com')}"}
    assert client.post(f"{API}/admin/staff", json={**NEW_STAFF, "roles": ["wizard"]}, headers=h).status_code == 422
    assert client.post(f"{API}/admin/staff", json=NEW_STAFF, headers=h).status_code == 201
    assert client.post(f"{API}/admin/staff", json=NEW_STAFF, headers=h).status_code == 409
