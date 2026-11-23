import secrets
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.modules.accounts.models import Membership, Patient, Staff
from app.modules.auth.schemas import PatientRegister

DUPLICATE = HTTPException(
    status.HTTP_409_CONFLICT, "An account with these details already exists"
)
BAD_LOGIN = HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")


def register_patient(db: Session, data: PatientRegister) -> tuple[Patient, Membership]:
    email = data.email.lower()
    exists = db.scalar(
        select(Patient.patient_id).where(
            or_(
                Patient.email == email,
                Patient.phone == data.phone,
                Patient.id_number == data.id_number,
            )
        )
    )
    if exists:  # FR-003: no duplicate accounts
        raise DUPLICATE

    patient = Patient(
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        id_number=data.id_number,
        date_of_birth=data.date_of_birth,
        email=email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        consent_given_at=datetime.now(timezone.utc),
        privacy_notice_version=get_settings().privacy_notice_version,
    )
    db.add(patient)
    try:
        db.flush()  # get patient_id
        membership = Membership(
            patient_id=patient.patient_id,
            membership_number=f"CC{patient.patient_id:08d}",  # FR-008, unique because id is unique
            qr_token=secrets.token_urlsafe(24),
            issued_date=date.today(),
        )
        db.add(membership)
        db.commit()
    except IntegrityError:  # race between two identical sign-ups
        db.rollback()
        raise DUPLICATE
    return patient, membership


def authenticate_patient(db: Session, email: str, password: str) -> Patient:
    patient = db.scalar(select(Patient).where(Patient.email == email.lower()))
    ok = verify_password(password, patient.password_hash if patient else DUMMY_HASH)
    if not patient or not ok or patient.account_status != "active":
        raise BAD_LOGIN
    return patient


def authenticate_staff(db: Session, email: str, password: str) -> Staff:
    staff = db.scalar(select(Staff).where(Staff.email == email.lower()))
    ok = verify_password(password, staff.password_hash if staff else DUMMY_HASH)
    if not staff or not ok or staff.account_status != "active":
        raise BAD_LOGIN
    return staff
