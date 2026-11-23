from datetime import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import ensure_branch_access, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Staff
from app.modules.branches.models import Branch, BranchHours

router = APIRouter(tags=["branches"])


class HoursIn(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    open_time: time
    close_time: time

    @model_validator(mode="after")
    def check_order(self):
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        return self


class HoursOut(HoursIn):
    model_config = {"from_attributes": True}


class BranchOut(BaseModel):
    branch_id: int
    branch_name: str
    address: str | None
    phone: str | None
    status: str
    hours: list[HoursOut]

    model_config = {"from_attributes": True}


class BranchCreate(BaseModel):
    branch_name: str = Field(min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)


class BranchUpdate(BaseModel):
    branch_name: str | None = Field(default=None, min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    status: Literal["active", "inactive"] | None = None


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get_branch_or_404(db: Session, branch_id: int) -> Branch:
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    return branch


# ---------- public: patients browse branches (FR-014 to FR-016) ----------


@router.get("/branches", response_model=list[BranchOut])
def list_branches(db: Session = Depends(get_db)):
    return db.scalars(select(Branch).where(Branch.status == "active").order_by(Branch.branch_name)).all()


@router.get("/branches/{branch_id}", response_model=BranchOut)
def get_branch(branch_id: int, db: Session = Depends(get_db)):
    branch = db.get(Branch, branch_id)
    if branch is None or branch.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    return branch


# ---------- staff: manage branches ----------


@router.post("/branches", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(
    data: BranchCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    branch = Branch(branch_name=data.branch_name.strip(), address=data.address, phone=data.phone)
    db.add(branch)
    db.flush()
    write_audit(
        db, actor_staff_id=admin.staff_id, action="branch.create", entity_type="branch",
        entity_id=branch.branch_id, details={"branch_name": branch.branch_name}, ip_address=_ip(request),
    )
    db.commit()
    return branch


@router.patch("/branches/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: int,
    data: BranchUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    branch = _get_branch_or_404(db, branch_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(branch, field, value)
    write_audit(
        db, actor_staff_id=admin.staff_id, action="branch.update", entity_type="branch",
        entity_id=branch.branch_id, details=changes, ip_address=_ip(request),
    )
    db.commit()
    return branch


@router.put("/branches/{branch_id}/hours", response_model=BranchOut)
def set_branch_hours(
    branch_id: int,
    hours: list[HoursIn],
    request: Request,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles("system_admin", "clinic_manager")),
):
    """Replace the weekly operating hours (FR-015). Days left out are closed."""
    branch = _get_branch_or_404(db, branch_id)
    ensure_branch_access(staff, branch_id)  # FR-017
    days = [h.day_of_week for h in hours]
    if len(days) != len(set(days)):
        raise HTTPException(422, "Each day of the week may appear only once")

    branch.hours.clear()
    db.flush()  # delete old rows before inserting, so the unique constraint is never hit
    branch.hours.extend(
        BranchHours(day_of_week=h.day_of_week, open_time=h.open_time, close_time=h.close_time) for h in hours
    )
    write_audit(
        db, actor_staff_id=staff.staff_id, action="branch.hours.set", entity_type="branch",
        entity_id=branch_id,
        details={"hours": [{"day": h.day_of_week, "open": h.open_time.isoformat(), "close": h.close_time.isoformat()} for h in hours]},
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(branch)
    return branch
