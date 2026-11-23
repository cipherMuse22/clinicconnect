"""Real-parallelism checks for the queue. Runs only against PostgreSQL (see test_booking_concurrency.py for setup).

WARNING: drops and recreates all tables in TEST_DATABASE_URL.
"""
import os
import threading
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.modules.accounts.models import Patient, Staff
from app.modules.appointments import service as svc
from app.modules.appointments.models import Appointment, AppointmentSlot
from app.modules.branches.models import Branch
from app.modules.queue import service as q
from app.modules.queue.models import QueueEntry
from app.modules.services.models import BranchService, Service

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run against real PostgreSQL")
N = 12


def test_simultaneous_check_ins_get_unique_consecutive_numbers_and_call_next_never_repeats():
    dt = svc.now_local() + timedelta(minutes=30)
    if dt.date() != svc.now_local().date() or (dt + timedelta(minutes=60)).date() != dt.date():
        pytest.skip("too close to midnight")
    engine = create_engine(URL, pool_size=N + 4)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with Session() as db:
        branch = Branch(branch_name="Queue Race")
        service = Service(service_name="Queue Race Service", estimated_duration_min=10)
        db.add_all([branch, service])
        db.flush()
        bs = BranchService(branch_id=branch.branch_id, service_id=service.service_id)
        nurses = [Staff(first_name="N", last_name=str(i), email=f"n{i}@example.com", password_hash="x") for i in range(4)]
        db.add_all([bs, *nurses])
        db.flush()
        slot = AppointmentSlot(
            branch_service_id=bs.branch_service_id, slot_date=dt.date(), start_time=dt.time().replace(microsecond=0),
            end_time=(dt + timedelta(minutes=30)).time().replace(microsecond=0), capacity=N,
        )
        db.add(slot)
        db.flush()
        appt_ids = []
        for i in range(N):
            p = Patient(
                first_name="P", last_name=str(i), id_number=f"Q{i:08d}", date_of_birth=date(1990, 1, 1),
                email=f"q{i}@example.com", phone=f"0840000{i:03d}", password_hash="x",
                consent_given_at=svc.now_local(), privacy_notice_version="t",
            )
            db.add(p)
            db.flush()
            appt_ids.append(svc.book_slot(db, p.patient_id, slot.slot_id).appointment_id)
        branch_id, nurse_ids = branch.branch_id, [n.staff_id for n in nurses]

    # ---- everybody checks in at the same instant
    errors, barrier = [], threading.Barrier(N)

    def go_check_in(appt_id):
        with Session() as s:
            barrier.wait()
            try:
                q.check_in(s, s.get(Appointment, appt_id), branch_id, method="branch_qr")
            except HTTPException as e:
                errors.append(e.detail)

    threads = [threading.Thread(target=go_check_in, args=(a,)) for a in appt_ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with Session() as s:
        numbers = sorted(s.scalars(select(QueueEntry.queue_number)).all())
    assert errors == [], errors
    assert numbers == list(range(1, N + 1))  # unique and gap-free (BR-007)

    # ---- four nurses all press "call next" repeatedly at once
    called, lock, barrier2 = [], threading.Lock(), threading.Barrier(len(nurse_ids))

    def nurse_loop(staff_id):
        with Session() as s:
            barrier2.wait()
            while True:
                try:
                    e = q.call_next(s, branch_id, staff_id)
                except HTTPException:
                    return  # nobody left
                with lock:
                    called.append(e.queue_id)

    threads = [threading.Thread(target=nurse_loop, args=(n,)) for n in nurse_ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(called) == N and len(set(called)) == N  # every patient called exactly once
    Base.metadata.drop_all(engine)
