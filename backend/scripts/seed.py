"""Seed roles, demo branches, services, opening hours and a first system admin. Safe to run repeatedly.

Run from backend/:   python -m scripts.seed
"""
import os
from datetime import timedelta, time

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.accounts.models import Role, Staff, StaffBranch, StaffRole
from app.modules.admin.router import ROLE_NAMES
from app.modules.appointments.service import generate_slots, now_local
from app.modules.branches.models import Branch, BranchHours
from app.modules.inventory.models import BranchStock, InventoryItem, ServiceItem
from app.modules.services.models import BranchService, Service

ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@clinicconnect.example.com")
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "ChangeMe123!")

BRANCHES = [
    ("ClinicConnect Sandton", "1 Demo Street, Sandton", "0110000000"),
    ("ClinicConnect Pretoria", "2 Sample Road, Pretoria", "0120000000"),
]

# FR-018 examples: (name, description, minutes)
SERVICES = [
    ("Adult vaccination", "Routine adult vaccinations given by a nurse.", 15),
    ("Flu vaccination", "Seasonal influenza vaccination.", 15),
    ("Baby immunisation", "Scheduled immunisations for infants.", 20),
    ("Blood pressure screening", "Quick blood pressure check.", 10),
    ("Blood glucose screening", "Finger-prick glucose test.", 10),
    ("Cholesterol screening", "Cholesterol test with results on the day.", 15),
    ("General nurse consultation", "Consultation with a registered nurse.", 30),
    ("Wellness check", "Basic wellness assessment.", 30),
]

# stock the demo services use: (item name, category, unit)
ITEMS = [
    ("Adult vaccine dose", "Vaccine", "dose"),
    ("Flu vaccine dose", "Vaccine", "dose"),
    ("Infant vaccine dose", "Vaccine", "dose"),
    ("Glucose test strip", "Test supply", "strip"),
    ("Cholesterol test cassette", "Test supply", "cassette"),
    ("Disposable gloves", "Consumable", "box"),
]
# service name -> item name (one unit used per appointment)
SERVICE_ITEMS = {
    "Adult vaccination": "Adult vaccine dose",
    "Flu vaccination": "Flu vaccine dose",
    "Baby immunisation": "Infant vaccine dose",
    "Blood glucose screening": "Glucose test strip",
    "Cholesterol screening": "Cholesterol test cassette",
}

# Monday to Friday 08:00-17:00, Saturday 08:00-13:00 (0 = Monday)
HOURS = [(d, time(8, 0), time(17, 0)) for d in range(5)] + [(5, time(8, 0), time(13, 0))]


def main() -> None:
    with SessionLocal() as db:
        for name in ROLE_NAMES:
            if not db.scalar(select(Role).where(Role.role_name == name)):
                db.add(Role(role_name=name))
        db.flush()

        branches = []
        for name, address, phone in BRANCHES:
            b = db.scalar(select(Branch).where(Branch.branch_name == name))
            if not b:
                b = Branch(branch_name=name, address=address, phone=phone)
                db.add(b)
                db.flush()
            if not b.hours:
                b.hours.extend(BranchHours(day_of_week=d, open_time=o, close_time=c) for d, o, c in HOURS)
            branches.append(b)

        services = []
        for name, desc, minutes in SERVICES:
            s = db.scalar(select(Service).where(Service.service_name == name))
            if not s:
                s = Service(service_name=name, description=desc, estimated_duration_min=minutes)
                db.add(s)
                db.flush()
            services.append(s)

        for b in branches:
            for s in services:
                exists = db.scalar(
                    select(BranchService.branch_service_id).where(
                        BranchService.branch_id == b.branch_id, BranchService.service_id == s.service_id
                    )
                )
                if not exists:
                    db.add(BranchService(branch_id=b.branch_id, service_id=s.service_id))

        db.flush()

        # inventory: items, a stock record per branch (50 on hand, minimum 10), and the service links
        admin_for_stock = db.scalar(select(Staff).where(Staff.email == ADMIN_EMAIL))
        items = {}
        for name, category, unit in ITEMS:
            it = db.scalar(select(InventoryItem).where(InventoryItem.item_name == name))
            if not it:
                it = InventoryItem(item_name=name, item_category=category, unit=unit)
                db.add(it)
                db.flush()
            items[name] = it
        for b in branches:
            for it in items.values():
                if not db.scalar(select(BranchStock.branch_stock_id).where(BranchStock.branch_id == b.branch_id, BranchStock.item_id == it.item_id)):
                    db.add(BranchStock(branch_id=b.branch_id, item_id=it.item_id, quantity=50, minimum_quantity=10))
        for svc_name, item_name in SERVICE_ITEMS.items():
            svc_row = next(x for x in services if x.service_name == svc_name)
            if not db.scalar(select(ServiceItem.service_item_id).where(ServiceItem.service_id == svc_row.service_id, ServiceItem.item_id == items[item_name].item_id)):
                db.add(ServiceItem(service_id=svc_row.service_id, item_id=items[item_name].item_id, quantity_per_service=1))
        db.flush()

        # 14 days of bookable slots (2 places each) for every offered service; safe to re-run
        today = now_local().date()
        for bs in db.scalars(select(BranchService)).all():
            generate_slots(db, bs, bs.service, today, today + timedelta(days=13), capacity=2)

        if not db.scalar(select(Staff).where(Staff.email == ADMIN_EMAIL)):
            admin = Staff(first_name="System", last_name="Admin", email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD))
            admin.roles.append(StaffRole(role=db.scalar(select(Role).where(Role.role_name == "system_admin"))))
            admin.branches.append(StaffBranch(branch_id=branches[0].branch_id))
            db.add(admin)
        db.commit()
    print(f"Seeded. Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}  (change this password)")


if __name__ == "__main__":
    main()
