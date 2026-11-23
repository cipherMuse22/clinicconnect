"""Proves the last place in a slot can never be taken twice.

SQLite cannot show true parallelism, so this test only runs against a real PostgreSQL:

    createdb clinicconnect_test      (or create it in pgAdmin / docker exec)
    set TEST_DATABASE_URL=postgresql+psycopg://clinic:clinic_dev_pw@localhost:5432/clinicconnect_test   (PowerShell: $env:TEST_DATABASE_URL="...")
    pytest tests/test_booking_concurrency.py

WARNING: it drops and recreates all tables in that database. Never point it at your real data.
"""
import os
import threading
from datetime import date, time, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.modules.accounts.models import Patient
from app.modules.appointments import service as svc
from app.modules.appointments.models import Appointment, AppointmentSlot
from app.modules.branches.models import Branch
from app.modules.services.models import BranchService, Service

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run against real PostgreSQL")

CAPACITY = 3
ATTEMPTS = 20


def test_many_patients_racing_for_a_slot_never_overbook():
    engine = create_engine(URL, pool_size=ATTEMPTS + 2)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with Session() as db:
        branch = Branch(branch_name="Race Branch")
        service = Service(service_name="Race Service", estimated_duration_min=30)
        db.add_all([branch, service])
        db.flush()
        bs = BranchService(branch_id=branch.branch_id, service_id=service.service_id)
        db.add(bs)
        db.flush()
        day = svc.now_local().date() + timedelta(days=5)
        slot = AppointmentSlot(branch_service_id=bs.branch_service_id, slot_date=day, start_time=time(9), end_time=time(9, 30), capacity=CAPACITY)
        db.add(slot)
        patients = []
        for i in range(ATTEMPTS):
            p = Patient(
                first_name="P", last_name=str(i), id_number=f"RACE{i:06d}", date_of_birth=date(1990, 1, 1),
                email=f"race{i}@example.com", phone=f"0830000{i:03d}", password_hash="x",
                consent_given_at=svc.now_local(), privacy_notice_version="t",
            )
            db.add(p)
            patients.append(p)
        db.commit()
        slot_id = slot.slot_id
        patient_ids = [p.patient_id for p in patients]

    results = []
    barrier = threading.Barrier(ATTEMPTS)

    def attempt(pid):
        with Session() as s:
            barrier.wait()  # everyone fires at the same moment
            try:
                svc.book_slot(s, pid, slot_id)
                results.append("ok")
            except HTTPException as e:
                results.append(e.status_code)

    threads = [threading.Thread(target=attempt, args=(pid,)) for pid in patient_ids]
    [t.start() for t in threads]
    [t.join() for t in threads]

    with Session() as s:
        booked = s.scalar(select(func.count()).select_from(Appointment).where(Appointment.slot_id == slot_id))
        counter = s.scalar(select(AppointmentSlot.booked_count).where(AppointmentSlot.slot_id == slot_id))
    assert results.count("ok") == CAPACITY
    assert results.count(409) == ATTEMPTS - CAPACITY
    assert booked == CAPACITY and counter == CAPACITY
    Base.metadata.drop_all(engine)
