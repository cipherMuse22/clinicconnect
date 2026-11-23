"""Seed roles, a demo branch and a first system admin.

Run from backend/:   python -m scripts.seed
"""
import os

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.accounts.models import Role, Staff, StaffBranch, StaffRole
from app.modules.admin.router import ROLE_NAMES
from app.modules.branches.models import Branch

ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@clinicconnect.example.com")
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "ChangeMe123!")


def main() -> None:
    with SessionLocal() as db:
        for name in ROLE_NAMES:
            if not db.scalar(select(Role).where(Role.role_name == name)):
                db.add(Role(role_name=name))
        db.flush()

        branch = db.scalar(select(Branch).where(Branch.branch_name == "ClinicConnect Sandton"))
        if not branch:
            branch = Branch(branch_name="ClinicConnect Sandton", address="1 Demo Street, Sandton", phone="0110000000")
            db.add(branch)
            db.flush()

        if not db.scalar(select(Staff).where(Staff.email == ADMIN_EMAIL)):
            admin = Staff(first_name="System", last_name="Admin", email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD))
            admin.roles.append(StaffRole(role=db.scalar(select(Role).where(Role.role_name == "system_admin"))))
            admin.branches.append(StaffBranch(branch_id=branch.branch_id))
            db.add(admin)
        db.commit()
    print(f"Seeded. Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}  (change this password)")


if __name__ == "__main__":
    main()
