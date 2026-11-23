from sqlalchemy import select

from app.modules.accounts.models import Staff
from app.modules.audit.models import AuditLog
from tests.conftest import make_staff, staff_token
from tests.test_appointments import book, first_slot, patient, world  # noqa: F401

API = "/api/v1"


def hdr(client, db, email, role, branch_ids=(1,)):
    if not db.scalar(select(Staff.staff_id).where(Staff.email == email)):  # reuse the account if the test asks twice
        make_staff(db, email, role, branch_ids=branch_ids)
    return {"Authorization": f"Bearer {staff_token(client, email)}"}


def setup_stock(client, db, qty=10, minimum=5):
    """An inventory manager at branch 1, one item, and a stock record for it."""
    im = hdr(client, db, "inv@clinic.example.com", "inventory_manager", (1,))
    item = client.post(f"{API}/inventory/items", json={"item_name": "Flu vaccine dose", "item_category": "Vaccine", "unit": "dose"}, headers=im).json()
    r = client.post(f"{API}/branches/1/stock", json={"item_id": item["item_id"], "initial_quantity": qty, "minimum_quantity": minimum}, headers=im)
    assert r.status_code == 201, r.text
    return im, item["item_id"]


# ------------------------------------------------------------------ catalogue and stock records


def test_item_catalogue_permissions_and_uniqueness(client, db_session, seeded):
    body = {"item_name": "Glucose strip", "unit": "strip"}
    assert client.post(f"{API}/inventory/items", json=body).status_code == 401
    rec = hdr(client, db_session, "rec@clinic.example.com", "receptionist")
    assert client.post(f"{API}/inventory/items", json=body, headers=rec).status_code == 403
    assert client.get(f"{API}/inventory/items", headers=rec).status_code == 403
    im = hdr(client, db_session, "inv@clinic.example.com", "inventory_manager")
    assert client.post(f"{API}/inventory/items", json=body, headers=im).status_code == 201
    assert client.post(f"{API}/inventory/items", json=body, headers=im).status_code == 409
    assert [i["item_name"] for i in client.get(f"{API}/inventory/items", headers=im).json()] == ["Glucose strip"]


def test_stock_record_created_with_initial_movement(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session, qty=10, minimum=5)
    stock = client.get(f"{API}/branches/1/stock", headers=im).json()
    assert len(stock) == 1 and stock[0]["quantity"] == 10 and stock[0]["low_stock"] is False and stock[0]["unit"] == "dose"
    history = client.get(f"{API}/branches/1/stock/{item_id}/movements", headers=im).json()
    assert history[0]["movement_type"] == "received" and history[0]["reason"] == "Initial stock" and history[0]["quantity_after"] == 10
    assert client.post(f"{API}/branches/1/stock", json={"item_id": item_id}, headers=im).status_code == 409  # already tracked
    assert client.post(f"{API}/branches/1/stock", json={"item_id": 999}, headers=im).status_code == 404


def test_inventory_manager_limited_to_assigned_branches(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session)
    assert client.get(f"{API}/branches/2/stock", headers=im).status_code == 403  # FR-017
    assert client.post(f"{API}/branches/2/stock", json={"item_id": item_id}, headers=im).status_code == 403
    admin = hdr(client, db_session, "admin@clinic.example.com", "system_admin", ())
    assert client.post(f"{API}/branches/2/stock", json={"item_id": item_id, "initial_quantity": 3}, headers=admin).status_code == 201
    assert client.get(f"{API}/branches/99/stock", headers=admin).status_code == 404


# ------------------------------------------------------------------ movements


def test_received_used_adjusted_and_history(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session, qty=10)
    url = f"{API}/branches/1/stock/{item_id}/movements"
    assert client.post(url, json={"movement_type": "received", "quantity": 20}, headers=im).json()["quantity_after"] == 30  # FR-048
    assert client.post(url, json={"movement_type": "used", "quantity": 4}, headers=im).json()["quantity_change"] == -4
    r = client.post(url, json={"movement_type": "adjusted", "quantity": -2, "reason": "Damaged in transit"}, headers=im)
    assert r.json()["quantity_after"] == 24
    assert client.get(f"{API}/branches/1/stock", headers=im).json()[0]["quantity"] == 24
    assert [m["movement_type"] for m in client.get(url, headers=im).json()] == ["adjusted", "used", "received", "received"]


def test_stock_never_goes_negative_and_bad_movements_rejected(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session, qty=3)
    url = f"{API}/branches/1/stock/{item_id}/movements"
    assert client.post(url, json={"movement_type": "used", "quantity": 4}, headers=im).status_code == 409
    assert client.get(f"{API}/branches/1/stock", headers=im).json()[0]["quantity"] == 3  # unchanged
    assert client.post(url, json={"movement_type": "adjusted", "quantity": -10, "reason": "x"}, headers=im).status_code == 409
    for bad in (
        {"movement_type": "received", "quantity": 0},
        {"movement_type": "received", "quantity": -5},
        {"movement_type": "adjusted", "quantity": 5},  # reason required
        {"movement_type": "adjusted", "quantity": 5, "reason": "  "},
        {"movement_type": "stolen", "quantity": 1},
    ):
        assert client.post(url, json=bad, headers=im).status_code == 422
    assert client.post(url.replace(f"/{item_id}/", "/999/"), json={"movement_type": "received", "quantity": 1}, headers=im).status_code == 404


def test_only_inventory_roles_can_change_stock_but_nurse_and_manager_can_view(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session)
    nurse = hdr(client, db_session, "nurse@clinic.example.com", "nurse")
    mgr = hdr(client, db_session, "mgr@clinic.example.com", "clinic_manager")
    rec = hdr(client, db_session, "rec@clinic.example.com", "receptionist")
    url = f"{API}/branches/1/stock/{item_id}/movements"
    for h in (nurse, mgr, rec):
        assert client.post(url, json={"movement_type": "used", "quantity": 1}, headers=h).status_code == 403
    assert client.get(f"{API}/branches/1/stock", headers=nurse).status_code == 200
    assert client.get(f"{API}/branches/1/stock", headers=mgr).status_code == 200
    assert client.get(f"{API}/branches/1/stock", headers=rec).status_code == 403


# ------------------------------------------------------------------ low stock and availability


def test_low_stock_alert_uses_minimum_level(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session, qty=6, minimum=5)
    mgr = hdr(client, db_session, "mgr@clinic.example.com", "clinic_manager")
    assert client.get(f"{API}/branches/1/stock/low", headers=mgr).json() == []
    client.post(f"{API}/branches/1/stock/{item_id}/movements", json={"movement_type": "used", "quantity": 2}, headers=im)
    low = client.get(f"{API}/branches/1/stock/low", headers=mgr).json()  # FR-049
    assert len(low) == 1 and low[0]["quantity"] == 4 and low[0]["low_stock"] is True
    client.patch(f"{API}/branches/1/stock/{item_id}", json={"minimum_quantity": 2}, headers=im)
    assert client.get(f"{API}/branches/1/stock/low", headers=mgr).json() == []


def test_mark_item_unavailable(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session)
    r = client.patch(f"{API}/branches/1/stock/{item_id}", json={"availability_status": "unavailable"}, headers=im)
    assert r.status_code == 200 and r.json()["availability_status"] == "unavailable"
    assert client.patch(f"{API}/branches/1/stock/{item_id}", json={"availability_status": "gone"}, headers=im).status_code == 422
    assert client.patch(f"{API}/branches/1/stock/999", json={"minimum_quantity": 1}, headers=im).status_code == 404


# ------------------------------------------------------------------ booking considers stock (FR-051)


def link(client, db, service_id, item_id, per=1):
    admin = hdr(client, db, "admin@clinic.example.com", "system_admin", ())
    r = client.put(f"{API}/services/{service_id}/items/{item_id}", json={"quantity_per_service": per}, headers=admin)
    assert r.status_code == 200, r.text
    return admin


def test_service_without_stock_cannot_be_booked_until_restocked(client, world):
    db = world["db"]
    sid = world["service"].service_id
    slot = first_slot(world, client)  # note the slot first: once stock is short, the slot list is empty
    im, item_id = setup_stock(client, db, qty=0, minimum=2)  # a record exists but nothing in it
    link(client, db, sid, item_id)
    h = patient(client)
    assert client.get(f"{API}/branches/1/services/{sid}/slots", params={"date": world["date"].isoformat()}).json() == []
    assert book(client, h, slot["slot_id"]).status_code == 409
    listed = client.get(f"{API}/branches/1/services").json()
    assert listed[0]["in_stock"] is False

    client.post(f"{API}/branches/1/stock/{item_id}/movements", json={"movement_type": "received", "quantity": 5}, headers=im)
    assert client.get(f"{API}/branches/1/services").json()[0]["in_stock"] is True
    assert book(client, h, slot["slot_id"]).status_code == 201
    # stock at the other branch is separate: branch 2 holds none of this item
    assert client.get(f"{API}/branches/2/services").json()[0]["in_stock"] is False


def test_unavailable_stock_item_blocks_booking_and_quantity_per_service_matters(client, world):
    db = world["db"]
    sid = world["service"].service_id
    slot_id = first_slot(world, client)["slot_id"]
    im, item_id = setup_stock(client, db, qty=2, minimum=0)
    link(client, db, sid, item_id, per=3)  # each appointment needs 3 but only 2 held
    assert book(client, patient(client), slot_id).status_code == 409
    link(client, db, sid, item_id, per=1)
    assert book(client, patient(client, 2), slot_id).status_code == 201
    client.patch(f"{API}/branches/1/stock/{item_id}", json={"availability_status": "unavailable"}, headers=im)
    assert book(client, patient(client, 3), slot_id).status_code == 409


def test_service_item_links_admin_only_and_removable(client, world):
    db = world["db"]
    sid = world["service"].service_id
    im, item_id = setup_stock(client, db)
    assert client.put(f"{API}/services/{sid}/items/{item_id}", json={}, headers=im).status_code == 403
    admin = link(client, db, sid, item_id, per=2)
    assert client.get(f"{API}/services/{sid}/items", headers=im).json() == [
        {"item_id": item_id, "item_name": "Flu vaccine dose", "unit": "dose", "quantity_per_service": 2}
    ]
    assert client.put(f"{API}/services/{sid}/items/999", json={}, headers=admin).status_code == 404
    assert client.put(f"{API}/services/{sid}/items/{item_id}", json={"quantity_per_service": 0}, headers=admin).status_code == 422
    assert client.delete(f"{API}/services/{sid}/items/{item_id}", headers=admin).status_code == 204
    assert client.delete(f"{API}/services/{sid}/items/{item_id}", headers=admin).status_code == 404
    assert book(client, patient(client), first_slot(world, client)["slot_id"]).status_code == 201  # no stock rule any more


def test_inventory_changes_are_audited(client, db_session, seeded):
    im, item_id = setup_stock(client, db_session)
    client.patch(f"{API}/branches/1/stock/{item_id}", json={"minimum_quantity": 9}, headers=im)
    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert {"inventory.item.create", "inventory.stock.create", "inventory.stock.update"} <= actions
