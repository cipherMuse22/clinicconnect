import io
from datetime import date, datetime, time

import segno
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import ensure_branch_access, get_current_patient, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Patient, Staff
from app.modules.appointments.models import Appointment
from app.modules.appointments.service import now_local
from app.modules.branches.models import Branch
from app.modules.queue import service as q
from app.modules.queue.models import QueueEntry

router = APIRouter(tags=["queue"])

FRONT_DESK = ("receptionist", "clinic_manager", "system_admin")
QUEUE_VIEWERS = ("receptionist", "nurse", "clinic_manager", "system_admin")


# ------------------------------------------------------------------ schemas


class PatientCheckIn(BaseModel):
    branch_token: str = Field(description="From the QR code displayed at the branch")
    appointment_reference: str | None = Field(default=None, description="Needed only if you have several appointments today")


class StaffCheckIn(BaseModel):
    appointment_reference: str | None = None
    qr_token: str | None = Field(default=None, description="The token inside the patient's membership QR code")

    @model_validator(mode="after")
    def one_of(self):
        if not self.appointment_reference and not self.qr_token:
            raise ValueError("Provide an appointment_reference or a qr_token")
        return self


class StatusChange(BaseModel):
    status: str


class QueueOut(BaseModel):
    queue_id: int
    queue_number: int
    queue_status: str
    queue_date: date
    branch_id: int
    branch_name: str
    appointment_reference: str
    service_name: str
    appointment_time: time
    check_in_time: datetime
    people_ahead: int
    estimated_wait_minutes: int
    estimate_note: str = "Estimate only. Actual waiting time may differ."


class StaffQueueOut(QueueOut):
    patient_name: str
    called_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None


def _base(db: Session, e: QueueEntry) -> dict:
    ahead, wait = q.queue_position(db, e)
    slot = e.appointment.slot
    bs = slot.branch_service
    return dict(
        queue_id=e.queue_id, queue_number=e.queue_number, queue_status=e.queue_status, queue_date=e.queue_date,
        branch_id=e.branch_id, branch_name=bs.branch.branch_name, appointment_reference=e.appointment.appointment_reference,
        service_name=bs.service.service_name, appointment_time=slot.start_time, check_in_time=e.check_in_time,
        people_ahead=ahead, estimated_wait_minutes=wait,
    )


def to_queue_out(db: Session, e: QueueEntry) -> QueueOut:
    return QueueOut(**_base(db, e))


def to_staff_out(db: Session, e: QueueEntry) -> StaffQueueOut:
    p = e.appointment.patient
    return StaffQueueOut(
        **_base(db, e), patient_name=f"{p.first_name} {p.last_name}",
        called_at=e.called_at, started_at=e.started_at, completed_at=e.completed_at,
    )


def _branch_or_404(db: Session, branch_id: int) -> Branch:
    b = db.get(Branch, branch_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    return b


def _entry_for_staff(db: Session, staff: Staff, queue_id: int) -> QueueEntry:
    e = db.get(QueueEntry, queue_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Queue entry not found")
    ensure_branch_access(staff, e.branch_id)
    return e


# ------------------------------------------------------------------ patient


@router.post("/me/check-in", response_model=QueueOut, status_code=status.HTTP_201_CREATED)
def patient_check_in(data: PatientCheckIn, patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    """FR-032: the patient scans the code shown at the branch. The branch comes from the code (BR-006)."""
    branch_id = q.branch_from_token(data.branch_token)
    if data.appointment_reference:
        appt = db.scalar(select(Appointment).where(Appointment.appointment_reference == data.appointment_reference.strip().upper()))
        if appt is None or appt.patient_id != patient.patient_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    else:
        appt = q.pick_single(q.todays_booked(db, patient.patient_id, branch_id))
    return to_queue_out(db, q.check_in(db, appt, branch_id, method="branch_qr"))


@router.get("/me/queue", response_model=QueueOut)
def my_queue_status(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    """FR-036: today's queue entry (the most recent if there are several)."""
    entry = db.scalar(
        select(QueueEntry)
        .join(Appointment, Appointment.appointment_id == QueueEntry.appointment_id)
        .where(Appointment.patient_id == patient.patient_id, QueueEntry.queue_date == now_local().date())
        .order_by(QueueEntry.check_in_time.desc())
        .limit(1)
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not in a queue today")
    return to_queue_out(db, entry)


# ------------------------------------------------------------------ staff: check in and view


@router.post("/branches/{branch_id}/check-in", response_model=StaffQueueOut, status_code=status.HTTP_201_CREATED)
def staff_check_in(
    branch_id: int, data: StaffCheckIn, db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*FRONT_DESK)),
):
    _branch_or_404(db, branch_id)
    ensure_branch_access(staff, branch_id)
    if data.appointment_reference:
        appt = db.scalar(select(Appointment).where(Appointment.appointment_reference == data.appointment_reference.strip().upper()))
        if appt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
        method = "reference"
    else:
        appt = q.appointment_for_membership_qr(db, data.qr_token.strip(), branch_id)
        method = "membership_qr"
    return to_staff_out(db, q.check_in(db, appt, branch_id, method=method, staff_id=staff.staff_id))


@router.get("/branches/{branch_id}/check-in-qr.png", response_class=Response)
def branch_check_in_qr(branch_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles(*FRONT_DESK))):
    """The QR code to display at the branch. Patients scan it in the app. It changes daily."""
    _branch_or_404(db, branch_id)
    ensure_branch_access(staff, branch_id)
    buf = io.BytesIO()
    segno.make(f"clinicconnect://checkin/{q.make_checkin_token(branch_id)}", error="m").save(buf, kind="png", scale=10, border=3)
    return Response(buf.getvalue(), media_type="image/png")


@router.get("/branches/{branch_id}/queue", response_model=list[StaffQueueOut])
def branch_queue(
    branch_id: int, day: date | None = Query(default=None, alias="date"), db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*QUEUE_VIEWERS)),
):
    _branch_or_404(db, branch_id)
    ensure_branch_access(staff, branch_id)
    entries = db.scalars(
        select(QueueEntry)
        .where(QueueEntry.branch_id == branch_id, QueueEntry.queue_date == (day or now_local().date()))
        .order_by(QueueEntry.queue_number)
    ).all()
    return [to_staff_out(db, e) for e in entries]


# ------------------------------------------------------------------ staff: run the queue


@router.post("/branches/{branch_id}/queue/call-next", response_model=StaffQueueOut)
def call_next_patient(
    branch_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles("nurse")),
):
    """FR-037"""
    _branch_or_404(db, branch_id)
    ensure_branch_access(staff, branch_id)
    return to_staff_out(db, q.call_next(db, branch_id, staff.staff_id))


@router.patch("/queue/{queue_id}/status", response_model=StaffQueueOut)
def update_queue_status(
    queue_id: int, data: StatusChange, db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*QUEUE_VIEWERS)),
):
    """FR-038, FR-039"""
    entry = _entry_for_staff(db, staff, queue_id)
    return to_staff_out(db, q.change_status(db, entry, data.status, staff.staff_id, is_nurse="nurse" in staff.role_names))


@router.post("/queue/{queue_id}/complete", response_model=StaffQueueOut)
def complete_visit(queue_id: int, db: Session = Depends(get_db), staff: Staff = Depends(require_roles("nurse"))):
    entry = _entry_for_staff(db, staff, queue_id)
    return to_staff_out(db, q.complete_visit(db, entry, staff.staff_id))
