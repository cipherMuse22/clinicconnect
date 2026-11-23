# ClinicConnect

Full-stack healthcare management portfolio project (fictional provider). See `docs/` for the SRS and diagrams.

```
backend/   FastAPI + PostgreSQL API        (Phases 1-2: accounts, membership, RBAC, audit, branches, services)
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

## Next steps

1. Phase 3: `appointment_slot` + booking with a row lock.
2. Scaffold `web/` (Vite React TS) and `mobile/` (`flutter create`).

## Known gaps (on purpose, for later)

- No refresh tokens or password reset yet (FR-005): add `PASSWORD_RESET` table and a refresh endpoint.
- No rate limiting on login.
- `SECRET_KEY` in `.env` must be replaced with a long random value outside development.
