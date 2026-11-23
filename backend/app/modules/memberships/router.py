import io

import segno
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_patient
from app.db.session import get_db
from app.modules.accounts.models import Patient
from app.modules.auth.schemas import MembershipOut, PatientOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=PatientOut)
def my_profile(patient: Patient = Depends(get_current_patient)):
    return patient


@router.get("/membership", response_model=MembershipOut)
def my_membership(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    db.refresh(patient, ["membership"])
    return patient.membership


@router.get("/membership/qr.png", response_class=Response)
def my_membership_qr(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    """QR image of the membership token (FR-010). Staff scan it to identify the patient."""
    db.refresh(patient, ["membership"])
    buf = io.BytesIO()
    segno.make(patient.membership.qr_token, error="m").save(buf, kind="png", scale=8, border=2)
    return Response(buf.getvalue(), media_type="image/png")
