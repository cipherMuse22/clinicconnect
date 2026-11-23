"""Stock can never go below zero, even when many people record usage at once. Needs real PostgreSQL
(see test_booking_concurrency.py for setup). WARNING: drops and recreates all tables in TEST_DATABASE_URL."""
import os
import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.modules.accounts.models import Staff
from app.modules.branches.models import Branch
from app.modules.inventory import service as inv
from app.modules.inventory.models import BranchStock, InventoryItem, StockMovement

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run against real PostgreSQL")

ON_HAND, ATTEMPTS = 5, 20


def test_simultaneous_use_never_overdraws_stock():
    engine = create_engine(URL, pool_size=ATTEMPTS + 2)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as db:
        branch, item = Branch(branch_name="Stock Race"), InventoryItem(item_name="Race item", unit="unit")
        staff = Staff(first_name="S", last_name="S", email="s@example.com", password_hash="x")
        db.add_all([branch, item, staff])
        db.flush()
        stock = BranchStock(branch_id=branch.branch_id, item_id=item.item_id, quantity=ON_HAND)
        db.add(stock)
        db.commit()
        stock_id, staff_id = stock.branch_stock_id, staff.staff_id

    results, barrier = [], threading.Barrier(ATTEMPTS)

    def use_one():
        with Session() as s:
            barrier.wait()
            try:
                inv.apply_movement(s, s.get(BranchStock, stock_id), staff_id, "used", -1, None)
                s.commit()
                results.append("ok")
            except HTTPException as e:
                results.append(e.status_code)

    threads = [threading.Thread(target=use_one) for _ in range(ATTEMPTS)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with Session() as s:
        quantity = s.scalar(select(BranchStock.quantity).where(BranchStock.branch_stock_id == stock_id))
        movements = len(s.scalars(select(StockMovement.movement_id)).all())
    assert results.count("ok") == ON_HAND and results.count(409) == ATTEMPTS - ON_HAND
    assert quantity == 0 and movements == ON_HAND  # no phantom movements from the refused attempts
    Base.metadata.drop_all(engine)
