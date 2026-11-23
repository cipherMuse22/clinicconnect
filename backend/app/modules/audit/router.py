import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import require_roles
from app.db.session import get_db
from app.modules.accounts.models import Staff
from app.modules.audit.models import AuditLog

router = APIRouter(tags=["audit"])


class AuditEntry(BaseModel):
    audit_id: int
    created_at: datetime
    actor_staff_id: int | None
    actor_email: str | None
    action: str
    entity_type: str
    entity_id: int | None
    details: dict | None
    ip_address: str | None


class AuditPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditEntry]


def _utc_bounds(day_from: date | None, day_to: date | None):
    """Clinic-local days to UTC instants, because audit times are stored in UTC."""
    tz = ZoneInfo(get_settings().clinic_timezone)
    lo = datetime.combine(day_from, time.min, tzinfo=tz).astimezone(timezone.utc) if day_from else None
    hi = datetime.combine(day_to + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc) if day_to else None
    return lo, hi


@router.get("/admin/audit-logs", response_model=AuditPage)
def audit_logs(
    action: str | None = Query(default=None, description="Exact action or a prefix such as 'branch.'"),
    entity_type: str | None = None,
    actor_staff_id: int | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    """NFR-005: review of important administrative actions, newest first. Administrators only."""
    conditions = []
    if action:
        conditions.append(AuditLog.action.startswith(action, autoescape=True))
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if actor_staff_id is not None:
        conditions.append(AuditLog.actor_staff_id == actor_staff_id)
    lo, hi = _utc_bounds(date_from, date_to)
    if lo:
        conditions.append(AuditLog.created_at >= lo)
    if hi:
        conditions.append(AuditLog.created_at < hi)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    rows = db.execute(
        select(AuditLog, Staff.email)
        .outerjoin(Staff, Staff.staff_id == AuditLog.actor_staff_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.audit_id.desc())
        .limit(limit).offset(offset)
    ).all()
    items = [
        AuditEntry(
            audit_id=a.audit_id, created_at=a.created_at, actor_staff_id=a.actor_staff_id, actor_email=email,
            action=a.action, entity_type=a.entity_type, entity_id=a.entity_id,
            details=json.loads(a.details) if a.details else None, ip_address=a.ip_address,
        )
        for a, email in rows
    ]
    return AuditPage(total=total, limit=limit, offset=offset, items=items)
