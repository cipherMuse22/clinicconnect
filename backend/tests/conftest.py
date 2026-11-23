import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.modules.accounts.models import Role, Staff, StaffBranch, StaffRole
from app.modules.admin.router import ROLE_NAMES
from app.modules.branches.models import Branch


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        yield session


@pytest.fixture()
def client(db_session):
    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(db_session):
    for name in ROLE_NAMES:
        db_session.add(Role(role_name=name))
    db_session.add(Branch(branch_name="Test Branch"))
    db_session.add(Branch(branch_name="Other Branch"))
    db_session.commit()


def make_staff(db, email: str, role: str, password: str = "StaffPass123!", branch_ids=()) -> Staff:
    s = Staff(first_name="T", last_name="User", email=email, password_hash=hash_password(password))
    s.roles.append(StaffRole(role=db.scalar(select(Role).where(Role.role_name == role))))
    for bid in branch_ids:
        s.branches.append(StaffBranch(branch_id=bid))
    db.add(s)
    db.commit()
    return s


def staff_token(client, email: str, password: str = "StaffPass123!") -> str:
    r = client.post("/api/v1/auth/staff/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


PATIENT = {
    "first_name": "Thandi",
    "last_name": "Nkosi",
    "id_number": "9001015800087",
    "date_of_birth": "1990-01-01",
    "email": "Thandi@Example.com",
    "phone": "+27 82 123 4567",
    "password": "Str0ngPassw0rd!",
    "consent": True,
}
