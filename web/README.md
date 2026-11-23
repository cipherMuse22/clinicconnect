# ClinicConnect staff dashboard (React + TypeScript + Vite)

One web app for all staff. The menu shows only what your role may use (the API enforces the same rules).

| Role | Sees |
|---|---|
| Receptionist | Queue (desk check-in, clinic QR, skip), Schedule (book / cancel for patients) |
| Nurse | Queue (call next, start visit, complete), Schedule (view), Inventory (view) |
| Clinic manager | Queue, Schedule, Inventory (view), Reports, Branches (hours, services, time slots for their branches) |
| Inventory manager | Inventory (receive, use, correct, add items) |
| System admin | Everything, plus Staff, Services, Branches (create, hours, services, time slots) and the Audit log |

## Run

The backend must be running (`uvicorn app.main:app --reload` in `backend/`). Then, in PowerShell:

```powershell
cd web
npm install
npm run dev
```

Open http://localhost:5173. Sign in with a staff account (the seeded admin is
`admin@clinicconnect.example.com`). Create other staff in http://localhost:8000/docs with `POST /admin/staff`.

If the API is not on `localhost:8000`, copy `.env.example` to `.env.local` and change `VITE_API_URL`.
`npm run build` type-checks and builds for production.

## Layout

```
src/api.ts       fetch wrapper, error text, and the types that mirror the API
src/auth.tsx     login, current staff, allowed branches, role checks
src/ui.tsx       useAsync (load / refresh / poll), Modal, Card, Badge
src/App.tsx      menu items and which roles may open them
src/pages/       Queue, Schedule, Inventory, Reports, Branches, Services, Staff, Audit, Login
```

The queue refreshes every 10 seconds. The login token lives in sessionStorage, so it clears when the tab closes.
