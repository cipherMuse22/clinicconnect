from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import ensure_branch_access, get_current_patient, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Patient, Staff
from app.modules.appointments import service as svc
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment, AppointmentSlot
from app.modules.branches.models import Branch
from app.modules.services.models import BranchService, Service

router = APIRouter(tags=["appointments"])

STAFF_BOOKERS = ("receptionist", "clinic_manager", "system_admin")


# ------------------------------------------------------------------ schemas


class SlotOut(BaseModel):
    slot_id: int
    slot_date: date
    start_time: time
    end_time: time
    capacity: int
    spots_left: int
    available: bool


class SlotGenerate(BaseModel):
    service_id: int
    from_date: date
    to_date: date
    capacity: int = Field(default=2, ge=1, le=50)


class BookRequest(BaseModel):
    slot_id: int


class StaffBookRequest(BookRequest):
    patient_id: int


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class RescheduleRequest(BaseModel):
    new_slot_id: int


class AppointmentOut(BaseModel):
    appointment_id: int
    appointment_reference: str
    status: str
    branch_id: int
    branch_name: str
    service_id: int
    service_name: str
    slot_id: int
    slot_date: date
    start_time: time
    end_time: time
    cancelled_at: datetime | None
    cancellation_reason: str | None


class StaffAppointmentOut(AppointmentOut):
    patient_id: int
    patient_name: str
    patient_phone: str
    membership_number: str | None


def to_out(a: Appointment) -> AppointmentOut:
    s = a.slot
    bs = s.branch_service
    return AppointmentOut(
        appointment_id=a.appointment_id,
        appointment_reference=a.appointment_reference,
        status=a.status,
        branch_id=bs.branch_id,
        branch_name=bs.branch.branch_name,
        service_id=bs.service_id,
        service_name=bs.service.service_name,
        slot_id=s.slot_id,
        slot_date=s.slot_date,
        start_time=s.start_time,
        end_time=s.end_time,
        cancelled_at=a.cancelled_at,
        cancellation_reason=a.cancellation_reason,
    )


def to_staff_out(a: Appointment) -> StaffAppointmentOut:
    p = a.patient
    return StaffAppointmentOut(
        **to_out(a).model_dump(),
        patient_id=p.patient_id,
        patient_name=f"{p.first_name} {p.last_name}",
        patient_phone=p.phone,
        membership_number=p.membership.membership_number if p.membership else None,
    )


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _own_appointment(db: Session, patient: Patient, appointment_id: int) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    # 404 (not 403) so patients cannot discover other patients' appointment ids
    if appt is None or appt.patient_id != patient.patient_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    return appt


def _staff_appointment(db: Session, staff: Staff, appointment_id: int) -> Appointment:
    appt = svc.get_active_appointment(db, appointment_id)
    ensure_branch_access(staff, appt.slot.branch_service.branch_id)  # FR-017
    return appt


# ------------------------------------------------------------------ public: availability (FR-024)


@router.get("/branches/{branch_id}/services/{service_id}/slots", response_model=list[SlotOut])
def list_slots(branch_id: int, service_id: int, day: date = Query(alias="date"), db: Session = Depends(get_db)):
    bs = db.scalar(
        select(BranchService).where(BranchService.branch_id == branch_id, BranchService.service_id == service_id)
    )
    if bs is None or bs.branch.status != "active" or bs.service.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch or service not found")
    if bs.availability_status != "available":
        return []
    now = svc.now_local()
    slots = db.scalars(
        select(AppointmentSlot)
        .where(AppointmentSlot.branch_service_id == bs.branch_service_id, AppointmentSlot.slot_date == day)
        .order_by(AppointmentSlot.start_time)
    ).all()
    return [
        SlotOut(
            slot_id=s.slot_id, slot_date=s.slot_date, start_time=s.start_time, end_time=s.end_time,
            capacity=s.capacity, spots_left=s.capacity - s.booked_count,
            available=s.booked_count < s.capacity and svc.slot_start(s) > now,
        )
        for s in slots
    ]


# ------------------------------------------------------------------ patient (FR-025 to FR-029)


@router.post("/me/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def book_my_appointment(
    data: BookRequest, patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)
):
    return to_out(svc.book_slot(db, patient.patient_id, data.slot_id))


@router.get("/me/appointments", response_model=list[AppointmentOut])
def my_appointments(
    scope: str = Query("all", pattern="^(upcoming|past|all)$"),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Appointment)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .where(Appointment.patient_id == patient.patient_id)
        .order_by(AppointmentSlot.slot_date, AppointmentSlot.start_time)
    ).all()
    now = svc.now_local()

    def is_upcoming(a: Appointment) -> bool:
        end = datetime.combine(a.slot.slot_date, a.slot.end_time)
        return a.status in ACTIVE_STATUSES and end >= now

    if scope == "upcoming":
        rows = [a for a in rows if is_upcoming(a)]
    elif scope == "past":
        rows = [a for a in rows if not is_upcoming(a)][::-1]  # newest first
    return [to_out(a) for a in rows]


@router.get("/me/appointments/{appointment_id}", response_model=AppointmentOut)
def my_appointment(appointment_id: int, patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    return to_out(_own_appointment(db, patient, appointment_id))


@router.post("/me/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_my_appointment(
    appointment_id: int,
    data: CancelRequest | None = None,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    appt = _own_appointment(db, patient, appointment_id)
    return to_out(svc.cancel_appointment(db, appt, data.reason if data else None, by_staff=False))


@router.post("/me/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_my_appointment(
    appointment_id: int,
    data: RescheduleRequest,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    appt = _own_appointment(db, patient, appointment_id)
    return to_out(svc.reschedule_appointment(db, appt, data.new_slot_id, by_staff=False))


# ------------------------------------------------------------------ staff (FR-031, UC-11)


@router.post("/appointments", response_model=StaffAppointmentOut, status_code=status.HTTP_201_CREATED)
def book_for_patient(
    data: StaffBookRequest,
    request: Request,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*STAFF_BOOKERS)),
):
    patient = db.get(Patient, data.patient_id)
    if patient is None or patient.account_status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    slot = db.get(AppointmentSlot, data.slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
    ensure_branch_access(staff, slot.branch_service.branch_id)
    appt = svc.book_slot(db, patient.patient_id, data.slot_id, booked_by_staff_id=staff.staff_id)
    write_audit(
        db, actor_staff_id=staff.staff_id, action="appointment.create_for_patient", entity_type="appointment",
        entity_id=appt.appointment_id, details={"patient_id": patient.patient_id, "slot_id": data.slot_id},
        ip_address=_ip(request),
    )
    db.commit()
    return to_staff_out(appt)


@router.get("/branches/{branch_id}/appointments", response_model=list[StaffAppointmentOut])
def branch_schedule(
    branch_id: int,
    day: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles("receptionist", "nurse", "clinic_manager", "system_admin")),
):
    """Appointments for one branch on one day (defaults to today). Contains no clinical information."""
    if db.get(Branch, branch_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    ensure_branch_access(staff, branch_id)
    day = day or svc.now_local().date()
    rows = db.scalars(
        select(Appointment)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .join(BranchService, BranchService.branch_service_id == AppointmentSlot.branch_service_id)
        .where(BranchService.branch_id == branch_id, AppointmentSlot.slot_date == day)
        .order_by(AppointmentSlot.start_time, Appointment.appointment_id)
    ).all()
    return [to_staff_out(a) for a in rows]


@router.post("/appointments/{appointment_id}/cancel", response_model=StaffAppointmentOut)
def cancel_for_patient(
    appointment_id: int,
    request: Request,
    data: CancelRequest | None = None,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*STAFF_BOOKERS)),
):
    appt = _staff_appointment(db, staff, appointment_id)
    svc.cancel_appointment(db, appt, data.reason if data else None, by_staff=True)
    write_audit(
        db, actor_staff_id=staff.staff_id, action="appointment.cancel_by_staff", entity_type="appointment",
        entity_id=appointment_id, ip_address=_ip(request),
    )
    db.commit()
    return to_staff_out(appt)


@router.post("/appointments/{appointment_id}/reschedule", response_model=StaffAppointmentOut)
def reschedule_for_patient(
    appointment_id: int,
    data: RescheduleRequest,
    request: Request,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*STAFF_BOOKERS)),
):
    appt = _staff_appointment(db, staff, appointment_id)
    svc.reschedule_appointment(db, appt, data.new_slot_id, by_staff=True)
    write_audit(
        db, actor_staff_id=staff.staff_id, action="appointment.reschedule_by_staff", entity_type="appointment",
        entity_id=appointment_id, details={"new_slot_id": data.new_slot_id}, ip_address=_ip(request),
    )
    db.commit()
    return to_staff_out(appt)


# ------------------------------------------------------------------ staff: create slots from opening hours


@router.post("/branches/{branch_id}/slots/generate")
def generate_slots(
    branch_id: int,
    data: SlotGenerate,
    request: Request,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles("system_admin", "clinic_manager")),
):
    if db.get(Branch, branch_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    ensure_branch_access(staff, branch_id)
    today = svc.now_local().date()
    if data.from_date < today:
        raise HTTPException(422, "from_date cannot be in the past")
    if data.to_date < data.from_date:
        raise HTTPException(422, "to_date must not be before from_date")
    if (data.to_date - data.from_date) > timedelta(days=30):
        raise HTTPException(422, "You can generate at most 31 days at a time")
    bs = db.scalar(
        select(BranchService).where(BranchService.branch_id == branch_id, BranchService.service_id == data.service_id)
    )
    if bs is None:
        raise HTTPException(404, "This branch does not offer that service")
    created = svc.generate_slots(db, bs, bs.service, data.from_date, data.to_date, data.capacity)
    write_audit(
        db, actor_staff_id=staff.staff_id, action="slots.generate", entity_type="branch",
        entity_id=branch_id, ip_address=_ip(request),
        details={"service_id": data.service_id, "from": data.from_date.isoformat(), "to": data.to_date.isoformat(),
                 "capacity": data.capacity, "created": created},
    )
    db.commit()
    return {"created": created}
