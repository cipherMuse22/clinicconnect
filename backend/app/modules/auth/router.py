from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginRequest,
    MembershipOut,
    PatientRegister,
    RegisterResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(data: PatientRegister, db: Session = Depends(get_db)):
    patient, membership = service.register_patient(db, data)
    return RegisterResponse(
        access_token=create_access_token(patient.patient_id, "patient"),
        membership=MembershipOut.model_validate(membership),
    )


@router.post("/login", response_model=TokenResponse)
def patient_login(data: LoginRequest, db: Session = Depends(get_db)):
    patient = service.authenticate_patient(db, data.email, data.password)
    return TokenResponse(access_token=create_access_token(patient.patient_id, "patient"))


@router.post("/staff/login", response_model=TokenResponse)
def staff_login(data: LoginRequest, db: Session = Depends(get_db)):
    staff = service.authenticate_staff(db, data.email, data.password)
    return TokenResponse(access_token=create_access_token(staff.staff_id, "staff"))
