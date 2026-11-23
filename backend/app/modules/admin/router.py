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
