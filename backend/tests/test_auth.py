from tests.conftest import PATIENT

API = "/api/v1"


def register(client, **over):
    return client.post(f"{API}/auth/register", json={**PATIENT, **over})


def test_register_creates_membership_and_token(client):
    r = register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["membership"]["membership_number"].startswith("CC")
    assert body["membership"]["qr_token"]


def test_register_requires_consent(client):
    assert register(client, consent=False).status_code == 422


def test_register_validates_fields(client):
    assert register(client, password="short").status_code == 422
    assert register(client, phone="abc").status_code == 422
    assert register(client, date_of_birth="2999-01-01").status_code == 422
    assert register(client, email="not-an-email").status_code == 422


def test_duplicate_email_phone_or_id_rejected(client):
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    # same ID number, different email and phone
    assert register(client, email="b@example.com", phone="0821111111").status_code == 409
    # same phone only
    assert register(client, email="c@example.com", id_number="ZZ1234567").status_code == 409


def test_email_is_case_insensitive_for_login(client):
    register(client)
    r = client.post(f"{API}/auth/login", json={"email": "thandi@example.com", "password": PATIENT["password"]})
    assert r.status_code == 200


def test_wrong_password_rejected(client):
    register(client)
    r = client.post(f"{API}/auth/login", json={"email": PATIENT["email"], "password": "wrong-password"})
    assert r.status_code == 401


def test_membership_requires_login_and_returns_own_data(client):
    assert client.get(f"{API}/me/membership").status_code == 401
    token = register(client).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    m = client.get(f"{API}/me/membership", headers=h)
    assert m.status_code == 200
    assert m.json()["membership_number"].startswith("CC")
    qr = client.get(f"{API}/me/membership/qr.png", headers=h)
    assert qr.status_code == 200 and qr.content[:4] == b"\x89PNG"


def test_two_patients_get_different_memberships(client):
    a = register(client).json()["membership"]
    b = register(client, email="b@example.com", phone="0821111111", id_number="8001015009087").json()["membership"]
    assert a["membership_number"] != b["membership_number"]
    assert a["qr_token"] != b["qr_token"]
