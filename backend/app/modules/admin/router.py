from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.modules.accounts.models import Role, Staff, StaffBranch, StaffRole
from app.modules.branches.models import Branch

router = APIRouter(prefix="/admin", tags=["admin"])

ROLE_NAMES = ["receptionist", "nurse", "clinic_manager", "inventory_manager", "system_admin"]


class StaffCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    roles: list[str] = Field(min_length=1)
    branch_ids: list[int] = []


class StaffOut(BaseModel):
    staff_id: int
    first_name: str
    last_name: str
    email: EmailStr
    account_status: str
    role_names: list[str]
    branch_ids: list[int]

    model_config = {"from_attributes": True}


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(
    data: StaffCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    """FR-006: staff accounts are created only by an authorised administrator."""
    unknown = set(data.roles) - set(ROLE_NAMES)
    if unknown:
        raise HTTPException(422, f"Unknown roles: {sorted(unknown)}")
    if db.scalar(select(Staff.staff_id).where(Staff.email == data.email.lower())):
        raise HTTPException(409, "A staff account with this email already exists")
    for bid in data.branch_ids:
        if db.get(Branch, bid) is None:
            raise HTTPException(422, f"Branch {bid} does not exist")

    staff = Staff(
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        email=data.email.lower(),
        password_hash=hash_password(data.password),
    )
    for name in data.roles:
        role = db.scalar(select(Role).where(Role.role_name == name))
        if role is None:
            raise HTTPException(500, f"Role {name} is not seeded; run scripts/seed.py")
        staff.roles.append(StaffRole(role=role))
    for bid in data.branch_ids:
        staff.branches.append(StaffBranch(branch_id=bid))
    db.add(staff)
    db.flush()
    write_audit(
        db,
        actor_staff_id=admin.staff_id,
        action="staff.create",
        entity_type="staff",
        entity_id=staff.staff_id,
        details={"email": staff.email, "roles": data.roles, "branch_ids": data.branch_ids},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return staff


# ---------------------------------------------------------------- manage existing staff


class StaffUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    roles: list[str] | None = Field(default=None, min_length=1)
    branch_ids: list[int] | None = None
    account_status: str | None = Field(default=None, pattern="^(active|inactive)$")


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get_staff_or_404(db: Session, staff_id: int) -> Staff:
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(404, "Staff member not found")
    return staff


def _other_active_admins(db: Session, exclude_staff_id: int) -> int:
    admins = db.scalars(select(Staff).where(Staff.account_status == "active", Staff.staff_id != exclude_staff_id)).all()
    return sum(1 for s in admins if "system_admin" in s.role_names)


@router.get("/staff", response_model=list[StaffOut])
def list_staff(db: Session = Depends(get_db), admin: Staff = Depends(require_roles("system_admin"))):
    return db.scalars(select(Staff).order_by(Staff.first_name, Staff.last_name)).all()


@router.patch("/staff/{staff_id}", response_model=StaffOut)
def update_staff(
    staff_id: int,
    data: StaffUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    """Change names, roles, branches or switch an account off. Roles and branches are replaced as a whole list."""
    staff = _get_staff_or_404(db, staff_id)
    changes: dict = {}

    if data.roles is not None:
        unknown = set(data.roles) - set(ROLE_NAMES)
        if unknown:
            raise HTTPException(422, f"Unknown roles: {sorted(unknown)}")
    new_roles = set(data.roles) if data.roles is not None else set(staff.role_names)
    new_status = data.account_status or staff.account_status

    # Never lock everybody out: the last active system admin cannot be demoted or deactivated.
    was_admin = "system_admin" in staff.role_names and staff.account_status == "active"
    will_be_admin = "system_admin" in new_roles and new_status == "active"
    if was_admin and not will_be_admin and _other_active_admins(db, staff.staff_id) == 0:
        raise HTTPException(409, "There must be at least one active system administrator")
    if staff.staff_id == admin.staff_id and new_status != "active":
        raise HTTPException(409, "You cannot deactivate your own account")

    if data.first_name is not None:
        staff.first_name = data.first_name.strip()
        changes["first_name"] = staff.first_name
    if data.last_name is not None:
        staff.last_name = data.last_name.strip()
        changes["last_name"] = staff.last_name
    if data.account_status is not None and data.account_status != staff.account_status:
        staff.account_status = data.account_status
        changes["account_status"] = data.account_status
    if data.roles is not None and set(data.roles) != set(staff.role_names):
        staff.roles.clear()
        db.flush()
        for name in dict.fromkeys(data.roles):
            staff.roles.append(StaffRole(role=db.scalar(select(Role).where(Role.role_name == name))))
        changes["roles"] = list(dict.fromkeys(data.roles))
    if data.branch_ids is not None and set(data.branch_ids) != set(staff.branch_ids):
        for bid in data.branch_ids:
            if db.get(Branch, bid) is None:
                raise HTTPException(422, f"Branch {bid} does not exist")
        staff.branches.clear()
        db.flush()
        for bid in dict.fromkeys(data.branch_ids):
            staff.branches.append(StaffBranch(branch_id=bid))
        changes["branch_ids"] = list(dict.fromkeys(data.branch_ids))

    if changes:
        write_audit(db, actor_staff_id=admin.staff_id, action="staff.update", entity_type="staff",
                    entity_id=staff.staff_id, details=changes, ip_address=_ip(request))
    db.commit()
    db.refresh(staff)
    return staff


@router.post("/staff/{staff_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_staff_password(
    staff_id: int,
    data: PasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    """An administrator sets a new password for someone who forgot theirs. The password itself is never logged."""
    staff = _get_staff_or_404(db, staff_id)
    staff.password_hash = hash_password(data.new_password)
    write_audit(db, actor_staff_id=admin.staff_id, action="staff.password_reset", entity_type="staff",
                entity_id=staff.staff_id, details={"email": staff.email}, ip_address=_ip(request))
    db.commit()


@router.get("/branches")
def list_all_branches(db: Session = Depends(get_db), admin: Staff = Depends(require_roles("system_admin"))):
    """Every branch including inactive ones (the public list hides them)."""
    from app.modules.branches.router import BranchOut

    rows = db.scalars(select(Branch).order_by(Branch.branch_name)).all()
    return [BranchOut.model_validate(b) for b in rows]


@router.get("/services")
def list_all_services(db: Session = Depends(get_db), admin: Staff = Depends(require_roles("system_admin"))):
    """Every service including inactive ones (the public list hides them)."""
    from app.modules.services.models import Service
    from app.modules.services.router import ServiceOut

    rows = db.scalars(select(Service).order_by(Service.service_name)).all()
    return [ServiceOut.model_validate(s) for s in rows]
