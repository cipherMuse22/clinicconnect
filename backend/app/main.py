from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.admin.router import router as admin_router
from app.modules.appointments.router import router as appointments_router
from app.modules.auth.router import router as auth_router
from app.modules.branches.router import router as branches_router
from app.modules.memberships.router import router as memberships_router
from app.modules.patients.router import router as patients_router
from app.modules.queue.router import router as queue_router
from app.modules.services.router import router as services_router

app = FastAPI(title="ClinicConnect API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"
app.include_router(auth_router, prefix=PREFIX)
app.include_router(memberships_router, prefix=PREFIX)
app.include_router(admin_router, prefix=PREFIX)
app.include_router(branches_router, prefix=PREFIX)
app.include_router(services_router, prefix=PREFIX)
app.include_router(appointments_router, prefix=PREFIX)
app.include_router(patients_router, prefix=PREFIX)
app.include_router(queue_router, prefix=PREFIX)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
