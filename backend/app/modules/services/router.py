from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import ensure_branch_access, require_roles
from app.db.session import get_db
from app.modules.accounts.models import Staff
from app.modules.branches.models import Branch
from app.modules.services.models import BranchService, Service

router = APIRouter(tags=["services"])


class ServiceOut(BaseModel):
    service_id: int
    service_name: str
    description: str | None
    estimated_duration_min: int
    status: str

    model_config = {"from_attributes": True}


class ServiceCreate(BaseModel):
    service_name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    estimated_duration_min: int = Field(gt=0, le=480)


class ServiceUpdate(BaseModel):
    service_name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    estimated_duration_min: int | None = Field(default=None, gt=0, le=480)
    status: Literal["active", "inactive"] | None = None


class BranchServiceOut(BaseModel):
    service_id: int
    service_name: str
    description: str | None
    estimated_duration_min: int
    availability_status: str
    available: bool  # FR-021: true only if the service is active and available at this branch


class BranchServiceIn(BaseModel):
    availability_status: Literal["available", "unavailable"] = "available"


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ---------- public ----------


@router.get("/services", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return db.scalars(select(Service).where(Service.status == "active").order_by(Service.service_name)).all()


@router.get("/branches/{branch_id}/services", response_model=list[BranchServiceOut])
def list_branch_services(branch_id: int, db: Session = Depends(get_db)):
    branch = db.get(Branch, branch_id)
    if branch is None or branch.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    rows = db.execute(
        select(BranchService, Service)
        .join(Service, Service.service_id == BranchService.service_id)
        .where(BranchService.branch_id == branch_id, Service.status == "active")
        .order_by(Service.service_name)
    ).all()
    return [
        BranchServiceOut(
            service_id=s.service_id,
            service_name=s.service_name,
            description=s.description,
            estimated_duration_min=s.estimated_duration_min,
            availability_status=bs.availability_status,
            available=bs.availability_status == "available",
        )
        for bs, s in rows
    ]


# ---------- staff: system-wide service catalogue (admin) ----------


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(
    data: ServiceCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    name = data.service_name.strip()
    if db.scalar(select(Service.service_id).where(Service.service_name == name)):
        raise HTTPException(409, "A service with this name already exists")
    service = Service(service_name=name, description=data.description, estimated_duration_min=data.estimated_duration_min)
    db.add(service)
    db.flush()
    write_audit(
        db, actor_staff_id=admin.staff_id, action="service.create", entity_type="service",
        entity_id=service.service_id, details={"service_name": name}, ip_address=_ip(request),
    )
    db.commit()
    return service


@router.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: int,
    data: ServiceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Staff = Depends(require_roles("system_admin")),
):
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "Service not found")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(service, field, value)
    write_audit(
        db, actor_staff_id=admin.staff_id, action="service.update", entity_type="service",
        entity_id=service_id, details=changes, ip_address=_ip(request),
    )
    db.commit()
    return service


# ---------- staff: which services a branch offers (FR-020, FR-050) ----------


@router.put("/branches/{branch_id}/services/{service_id}", response_model=BranchServiceOut)
def set_branch_service(
    branch_id: int,
    service_id: int,
    data: BranchServiceIn,
    request: Request,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles("system_admin", "clinic_manager")),
):
    """Offer a service at a branch, or change whether it is currently available there."""
    branch = db.get(Branch, branch_id)
    service = db.get(Service, service_id)
    if branch is None or service is None:
        raise HTTPException(404, "Branch or service not found")
    ensure_branch_access(staff, branch_id)  # FR-017

    bs = db.scalar(
        select(BranchService).where(BranchService.branch_id == branch_id, BranchService.service_id == service_id)
    )
    if bs is None:
        bs = BranchService(branch_id=branch_id, service_id=service_id)
        db.add(bs)
    bs.availability_status = data.availability_status
    write_audit(
        db, actor_staff_id=staff.staff_id, action="branch_service.set", entity_type="branch_service",
        entity_id=branch_id, ip_address=_ip(request),
        details={"service_id": service_id, "availability_status": data.availability_status},
    )
    db.commit()
    return BranchServiceOut(
        service_id=service.service_id,
        service_name=service.service_name,
        description=service.description,
        estimated_duration_min=service.estimated_duration_min,
        availability_status=bs.availability_status,
        available=bs.availability_status == "available" and service.status == "active",
    )


@router.delete("/branches/{branch_id}/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_branch_service(
    branch_id: int,
    service_id: int,
    request: Request,
    db: Session = Depends(get_db),
    staff: Staff = Depends(require_roles("system_admin", "clinic_manager")),
):
    ensure_branch_access(staff, branch_id)
    bs = db.scalar(
        select(BranchService).where(BranchService.branch_id == branch_id, BranchService.service_id == service_id)
    )
    if bs is None:
        raise HTTPException(404, "This branch does not offer that service")
    db.delete(bs)
    write_audit(
        db, actor_staff_id=staff.staff_id, action="branch_service.remove", entity_type="branch_service",
        entity_id=branch_id, details={"service_id": service_id}, ip_address=_ip(request),
    )
    db.commit()
