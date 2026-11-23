"""Operational reports for managers and administrators (FR-052 to FR-056).

Reports contain counts and averages only: no patient names and no clinical information.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import ensure_branch_access, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Patient, Staff
from app.modules.appointments.models import Appointment, AppointmentSlot
from app.modules.appointments.service import now_local
from app.modules.branches.models import Branch
from app.modules.inventory.models import BranchStock
from app.modules.queue.models import QueueEntry
from app.modules.services.models import BranchService, Service

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_ROLES = ("clinic_manager", "system_admin")
PENDING = {"booked", "checked_in", "in_progress"}


# ------------------------------------------------------------------ shared helpers


class Counts(BaseModel):
    total: int = 0
    completed: int = 0
    cancelled: int = 0
    no_show: int = 0
    pending: int = 0  # booked, checked in or in progress


def _bucket(status_value: str) -> str:
    return "pending" if status_value in PENDING else status_value  # completed, cancelled, no_show


def _add(c: Counts, status_value: str, n: int) -> None:
    c.total += n
    setattr(c, _bucket(status_value), getattr(c, _bucket(status_value)) + n)


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def date_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or now_local().date()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'from' must not be after 'to'")
    if (end - start) > timedelta(days=365):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A report can cover at most 366 days")
    return start, end


def resolve_branches(db: Session, staff: Staff, branch_id: int | None) -> list[int]:
    """Managers see their assigned branches; administrators see all (FR-017)."""
    if branch_id is not None:
        if db.get(Branch, branch_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
        ensure_branch_access(staff, branch_id)
        return [branch_id]
    if "system_admin" in staff.role_names:
        return list(db.scalars(select(Branch.branch_id).order_by(Branch.branch_id)))
    return sorted(staff.branch_ids)


def _appointment_rows(db: Session, branch_ids: list[int], start: date, end: date):
    return db.execute(
        select(
            AppointmentSlot.slot_date, BranchService.branch_id, Branch.branch_name,
            BranchService.service_id, Service.service_name, Appointment.status, func.count(),
        )
        .select_from(Appointment)
        .join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
        .join(BranchService, BranchService.branch_service_id == AppointmentSlot.branch_service_id)
        .join(Branch, Branch.branch_id == BranchService.branch_id)
        .join(Service, Service.service_id == BranchService.service_id)
        .where(BranchService.branch_id.in_(branch_ids), AppointmentSlot.slot_date >= start, AppointmentSlot.slot_date <= end)
        .group_by(AppointmentSlot.slot_date, BranchService.branch_id, Branch.branch_name,
                  BranchService.service_id, Service.service_name, Appointment.status)
    ).all()


def _queue_entries(db: Session, branch_ids: list[int], start: date, end: date) -> list[QueueEntry]:
    return list(
        db.scalars(
            select(QueueEntry).where(
                QueueEntry.branch_id.in_(branch_ids), QueueEntry.queue_date >= start, QueueEntry.queue_date <= end
            )
        )
    )


def _minutes(later, earlier) -> float | None:
    if later is None or earlier is None:
        return None
    return max((later - earlier).total_seconds() / 60, 0)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


# ------------------------------------------------------------------ appointment report (FR-052, FR-053)


class DayCounts(Counts):
    date: date


class NamedCounts(Counts):
    id: int
    name: str


class AppointmentReport(BaseModel):
    date_from: date
    date_to: date
    branch_ids: list[int]
    totals: Counts
    completion_rate: float
    cancellation_rate: float
    by_day: list[DayCounts]
    by_service: list[NamedCounts]
    by_branch: list[NamedCounts]


@router.get("/appointments", response_model=AppointmentReport)
def appointment_report(
    branch_id: int | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*REPORT_ROLES)),
):
    """Appointment totals and completed, cancelled, no-show and pending counts, by appointment date."""
    start, end = date_range(date_from, date_to)
    branches = resolve_branches(db, staff, branch_id)
    totals = Counts()
    days: dict[date, DayCounts] = {}
    services: dict[int, NamedCounts] = {}
    by_branch: dict[int, NamedCounts] = {}
    for day, b_id, b_name, s_id, s_name, st, n in _appointment_rows(db, branches, start, end):
        _add(totals, st, n)
        _add(days.setdefault(day, DayCounts(date=day)), st, n)
        _add(services.setdefault(s_id, NamedCounts(id=s_id, name=s_name)), st, n)
        _add(by_branch.setdefault(b_id, NamedCounts(id=b_id, name=b_name)), st, n)
    return AppointmentReport(
        date_from=start, date_to=end, branch_ids=branches, totals=totals,
        completion_rate=_rate(totals.completed, totals.total), cancellation_rate=_rate(totals.cancelled, totals.total),
        by_day=sorted(days.values(), key=lambda d: d.date),
        by_service=sorted(services.values(), key=lambda s: (-s.total, s.name)),
        by_branch=sorted(by_branch.values(), key=lambda b: b.name),
    )


# ------------------------------------------------------------------ queue report (FR-054)


class QueueDay(BaseModel):
    date: date
    checked_in: int
    completed: int
    avg_wait_minutes: float | None


class QueueReport(BaseModel):
    date_from: date
    date_to: date
    branch_ids: list[int]
    checked_in: int
    by_status: dict[str, int]
    avg_wait_minutes: float | None  # check-in until called
    avg_service_minutes: float | None  # service started until completed
    by_day: list[QueueDay]


@router.get("/queue", response_model=QueueReport)
def queue_report(
    branch_id: int | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*REPORT_ROLES)),
):
    start, end = date_range(date_from, date_to)
    branches = resolve_branches(db, staff, branch_id)
    entries = _queue_entries(db, branches, start, end)
    waits = [m for e in entries if (m := _minutes(e.called_at, e.check_in_time)) is not None]
    services = [m for e in entries if (m := _minutes(e.completed_at, e.started_at)) is not None]
    per_day: dict[date, list[QueueEntry]] = defaultdict(list)
    for e in entries:
        per_day[e.queue_date].append(e)
    by_day = [
        QueueDay(
            date=d, checked_in=len(es), completed=sum(e.queue_status == "completed" for e in es),
            avg_wait_minutes=_avg([m for e in es if (m := _minutes(e.called_at, e.check_in_time)) is not None]),
        )
        for d, es in sorted(per_day.items())
    ]
    return QueueReport(
        date_from=start, date_to=end, branch_ids=branches, checked_in=len(entries),
        by_status=dict(Counter(e.queue_status for e in entries)),
        avg_wait_minutes=_avg(waits), avg_service_minutes=_avg(services), by_day=by_day,
    )


# ------------------------------------------------------------------ branch performance (FR-055)


class BranchPerformance(BaseModel):
    branch_id: int
    branch_name: str
    appointments: Counts
    completion_rate: float
    cancellation_rate: float
    no_show_rate: float
    queue_checked_in: int
    avg_wait_minutes: float | None


@router.get("/branch-performance", response_model=list[BranchPerformance])
def branch_performance(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles(*REPORT_ROLES)),
):
    """One row per branch the caller may see, so branches can be compared."""
    start, end = date_range(date_from, date_to)
    branches = resolve_branches(db, staff, None)
    counts: dict[int, Counts] = {b: Counts() for b in branches}
    for _day, b_id, _bn, _sid, _sn, st, n in _appointment_rows(db, branches, start, end):
        _add(counts[b_id], st, n)
    waits: dict[int, list[float]] = defaultdict(list)
    seen: Counter = Counter()
    for e in _queue_entries(db, branches, start, end):
        seen[e.branch_id] += 1
        if (m := _minutes(e.called_at, e.check_in_time)) is not None:
            waits[e.branch_id].append(m)
    names = dict(db.execute(select(Branch.branch_id, Branch.branch_name).where(Branch.branch_id.in_(branches))).all())
    return [
        BranchPerformance(
            branch_id=b, branch_name=names[b], appointments=counts[b],
            completion_rate=_rate(counts[b].completed, counts[b].total),
            cancellation_rate=_rate(counts[b].cancelled, counts[b].total),
            no_show_rate=_rate(counts[b].no_show, counts[b].total),
            queue_checked_in=seen[b], avg_wait_minutes=_avg(waits[b]),
        )
        for b in sorted(branches, key=lambda x: names[x])
    ]


# ------------------------------------------------------------------ system summary (FR-056)


class SystemSummary(BaseModel):
    patients: int
    active_staff: int
    active_branches: int
    active_services: int
    appointments_today: int
    appointments_this_month: int
    queue_check_ins_today: int
    low_stock_items: int


@router.get("/system-summary", response_model=SystemSummary)
def system_summary(db: Session = Depends(get_db), admin: Staff = Depends(require_roles("system_admin"))):
    today = now_local().date()

    def count(stmt) -> int:
        return db.scalar(stmt) or 0

    def booked_between(a: date, b: date) -> int:
        return count(
            select(func.count()).select_from(Appointment).join(AppointmentSlot, AppointmentSlot.slot_id == Appointment.slot_id)
            .where(AppointmentSlot.slot_date >= a, AppointmentSlot.slot_date <= b, Appointment.status != "cancelled")
        )

    return SystemSummary(
        patients=count(select(func.count()).select_from(Patient).where(Patient.account_status == "active")),
        active_staff=count(select(func.count()).select_from(Staff).where(Staff.account_status == "active")),
        active_branches=count(select(func.count()).select_from(Branch).where(Branch.status == "active")),
        active_services=count(select(func.count()).select_from(Service).where(Service.status == "active")),
        appointments_today=booked_between(today, today),
        appointments_this_month=booked_between(today.replace(day=1), today + timedelta(days=31)),
        queue_check_ins_today=count(select(func.count()).select_from(QueueEntry).where(QueueEntry.queue_date == today)),
        low_stock_items=count(select(func.count()).select_from(BranchStock).where(BranchStock.quantity < BranchStock.minimum_quantity)),
    )
