from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.deps import get_current_patient, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Patient, Staff
from app.modules.notifications.models import Notification
from app.modules.notifications.reminders import send_due_reminders

router = APIRouter(tags=["notifications"])


class NotificationOut(BaseModel):
    notification_id: int
    notification_type: str
    message: str
    appointment_id: int | None
    sent_at: datetime
    read_at: datetime | None
    read: bool

    model_config = {"from_attributes": True}


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        notification_id=n.notification_id, notification_type=n.notification_type, message=n.message,
        appointment_id=n.appointment_id, sent_at=n.sent_at, read_at=n.read_at, read=n.read_at is not None,
    )


def _mine(patient: Patient):
    # the in-app inbox: the "in_app" rows, only for this patient
    return (Notification.patient_id == patient.patient_id, Notification.channel == "in_app")


@router.get("/me/notifications", response_model=list[NotificationOut])
def my_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
):
    """FR-045: notification history, newest first."""
    stmt = select(Notification).where(*_mine(patient))
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.sent_at.desc(), Notification.notification_id.desc()).limit(limit).offset(offset))
    return [_out(n) for n in rows]


@router.get("/me/notifications/unread-count")
def unread_count(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(Notification).where(*_mine(patient), Notification.read_at.is_(None)))
    return {"unread": n}


@router.post("/me/notifications/read-all")
def read_all(patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    res = db.execute(
        update(Notification).where(*_mine(patient), Notification.read_at.is_(None)).values(read_at=datetime.now().astimezone())
    )
    db.commit()
    return {"marked_read": res.rowcount}


@router.post("/me/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, patient: Patient = Depends(get_current_patient), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.patient_id != patient.patient_id:  # 404, so ids of other patients' messages stay hidden
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now().astimezone()
        db.commit()
    return _out(n)


@router.post("/admin/jobs/send-reminders")
def run_reminders_now(db: Session = Depends(get_db), admin: Staff = Depends(require_roles("system_admin"))):
    """Runs the reminder job immediately (it also runs automatically on a schedule)."""
    return {"sent": send_due_reminders(db)}
