from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.modules.accounts.models import Membership, Patient, Staff

router = APIRouter(tags=["patients"])


class PatientSearchResult(BaseModel):
    patient_id: int
    first_name: str
    last_name: str
    phone: str
    membership_number: str | None


@router.get("/patients/search", response_model=list[PatientSearchResult])
def search_patients(
    q: str = Query(min_length=3, max_length=60),
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles("receptionist")),
):
    """Reception lookup (section 3.2). Returns only basic contact details, never clinical information."""
    rows = db.execute(
        select(Patient, Membership.membership_number)
        .outerjoin(Membership, Membership.patient_id == Patient.patient_id)
        .where(
            Patient.account_status == "active",
            or_(
                Patient.first_name.icontains(q, autoescape=True),
                Patient.last_name.icontains(q, autoescape=True),
                Patient.phone.icontains(q, autoescape=True),
                Patient.email.icontains(q, autoescape=True),
                Membership.membership_number.icontains(q, autoescape=True),
            ),
        )
        .order_by(Patient.last_name, Patient.first_name)
        .limit(20)
    ).all()
    return [
        PatientSearchResult(
            patient_id=p.patient_id, first_name=p.first_name, last_name=p.last_name,
            phone=p.phone, membership_number=num,
        )
        for p, num in rows
    ]
