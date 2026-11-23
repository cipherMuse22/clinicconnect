# ClinicConnect

Full-stack healthcare management portfolio project (fictional provider). See `docs/` for the SRS and diagrams.

```
backend/   FastAPI + PostgreSQL API        (Phases 1-4: accounts, membership, RBAC, audit, branches, services, booking, check-in and queue)
web/       React staff dashboard           (next)
mobile/    Flutter patient app             (next)
docs/      SRS, ERD, use cases, architecture
```

## Run the backend

Prerequisites: Git, Docker Desktop, Python 3.12+ (3.13 works), VS Code.

```bash
# 1. database
docker compose up -d

# 2. backend
cd backend
python -m venv .venv
# Windows:    .venv\Scripts\activate
# Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
alembic upgrade head          # creates all tables
python -m scripts.seed        # roles, demo branch, first admin
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs to try the API.
Seeded admin: `admin@clinicconnect.example.com` / `ChangeMe123!` (change it; set `SEED_ADMIN_PASSWORD` before seeding).

Run tests (no database needed, they use in-memory SQLite): `pytest`

## What exists in Phase 1

| Endpoint | Who | Notes |
|---|---|---|
| `POST /api/v1/auth/register` | public | validates fields, requires POPIA consent, blocks duplicate email / phone / ID, issues membership number and QR token |
| `POST /api/v1/auth/login` | patient | |
| `POST /api/v1/auth/staff/login` | staff | |
| `GET /api/v1/me`, `/me/membership`, `/me/membership/qr.png` | patient | |
| `POST /api/v1/admin/staff` | `system_admin` | creates staff with roles and branches, writes an audit row |

## What exists in Phase 2

| Endpoint | Who | Notes |
|---|---|---|
| `GET /api/v1/branches`, `/branches/{id}` | public | active branches with weekly hours |
| `GET /api/v1/services` | public | active service catalogue |
| `GET /api/v1/branches/{id}/services` | public | services at a branch with an `available` flag |
| `POST/PATCH /api/v1/branches` | `system_admin` | create or edit a branch |
| `PUT /api/v1/branches/{id}/hours` | admin, or manager of that branch | replaces weekly hours |
| `POST/PATCH /api/v1/services` | `system_admin` | manage the service catalogue |
| `PUT/DELETE /api/v1/branches/{id}/services/{service_id}` | admin, or manager of that branch | offer a service at a branch, mark it unavailable |

After pulling Phase 2: `alembic upgrade head`, then `python -m scripts.seed` (adds 2 branches, 8 services, opening hours).

## What exists in Phase 3 (booking)

| Endpoint | Who | Notes |
|---|---|---|
| `GET /api/v1/branches/{b}/services/{s}/slots?date=YYYY-MM-DD` | public | slots with `spots_left` and `available` |
| `POST /api/v1/me/appointments` | patient | `{"slot_id": 1}`; returns a reference like `APT-3VQR4SZW` |
| `GET /api/v1/me/appointments?scope=upcoming\|past\|all` | patient | own appointments only |
| `POST /api/v1/me/appointments/{id}/cancel`, `/reschedule` | patient | blocked inside the cancellation cutoff (default 2 hours) |
| `POST /api/v1/appointments` | receptionist, manager, admin | book on behalf of a patient (`patient_id`, `slot_id`) |
| `POST /api/v1/appointments/{id}/cancel`, `/reschedule` | receptionist, manager, admin | no cutoff for staff |
| `GET /api/v1/branches/{b}/appointments?date=` | reception, nurse, manager, admin | day schedule, no clinical data |
| `GET /api/v1/patients/search?q=` | receptionist | name, phone, email or membership number |
| `POST /api/v1/branches/{b}/slots/generate` | admin, manager of that branch | builds slots from opening hours, max 31 days |

How double-booking is prevented: places are taken with one guarded `UPDATE ... WHERE booked_count < capacity`,
so two people can never take the last place. The database also has a `CHECK (booked_count <= capacity)`.
A patient can hold a slot only once (partial unique index), and a reschedule must stay at the same branch and service.

After pulling Phase 3: `pip install -r requirements.txt` (adds `tzdata`, needed on Windows), `alembic upgrade head`,
then `python -m scripts.seed` (adds 14 days of slots).

### Concurrency test (optional, needs real PostgreSQL)

```powershell
docker compose exec db psql -U clinic -d clinicconnect -c "CREATE DATABASE clinicconnect_test"
$env:TEST_DATABASE_URL="postgresql+psycopg://clinic:clinic_dev_pw@localhost:5432/clinicconnect_test"
pytest tests/test_booking_concurrency.py
```
It fires 20 simultaneous bookings at a 3-place slot and checks that exactly 3 succeed. It wipes only the `_test` database.

## What exists in Phase 4 (check-in and queue)

| Endpoint | Who | Notes |
|---|---|---|
| `POST /api/v1/me/check-in` | patient | `{"branch_token": "...", "appointment_reference": optional}`; the token comes from the QR shown at the branch |
| `GET /api/v1/me/queue` | patient | queue number, status, `people_ahead`, estimated wait (labelled as an estimate) |
| `POST /api/v1/branches/{b}/check-in` | receptionist, manager, admin | by `appointment_reference` or the membership `qr_token` |
| `GET /api/v1/branches/{b}/check-in-qr.png` | receptionist, manager, admin | the QR to display at the branch; changes daily |
| `GET /api/v1/branches/{b}/queue?date=` | reception, nurse, manager, admin | the day's queue |
| `POST /api/v1/branches/{b}/queue/call-next` | nurse | calls the lowest waiting number |
| `PATCH /api/v1/queue/{id}/status` | reception, nurse, manager, admin | `called`, `in_service` (nurse only), `skipped`, `cancelled`, `waiting` |
| `POST /api/v1/queue/{id}/complete` | nurse | finishes the visit, writes a `visit_record`, marks the appointment completed |

Rules: check-in must be at the appointment's own branch, on the day, and (for patients) from 60 minutes before the
slot until 30 minutes after it ends. Reception can check in outside that window. Cancelled, completed and
already checked-in appointments are refused. Queue numbers restart each day at each branch and are issued by an
atomic counter, so simultaneous check-ins never clash. Two nurses pressing "call next" together never call the same
patient. "People ahead" counts only patients still waiting.

After pulling Phase 4: `alembic upgrade head`. No new packages. The optional concurrency tests are
`tests/test_booking_concurrency.py` and `tests/test_queue_concurrency.py` (see the instructions above).

## Next steps

1. Phase 5: notifications (booking, reminders, cancellation, queue updates).
2. Phase 6: inventory and stock. Phase 7: reports and audit viewer.
3. Scaffold `web/` (Vite React TS) and `mobile/` (`flutter create`).

## Known gaps (on purpose, for later)

- No refresh tokens or password reset yet (FR-005): add `PASSWORD_RESET` table and a refresh endpoint.
- No rate limiting on login.
- `SECRET_KEY` in `.env` must be replaced with a long random value outside development.
