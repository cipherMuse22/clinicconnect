import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.admin.router import router as admin_router
from app.modules.appointments.router import router as appointments_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.branches.router import router as branches_router
from app.modules.inventory.router import router as inventory_router
from app.modules.memberships.router import router as memberships_router
from app.modules.notifications.reminders import run_scheduled_reminders
from app.modules.notifications.router import router as notifications_router
from app.modules.patients.router import router as patients_router
from app.modules.queue.router import router as queue_router
from app.modules.reports.router import router as reports_router
from app.modules.services.router import router as services_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the reminder scheduler with the server. Tests do not run this, so they stay quiet."""
    settings = get_settings()
    scheduler = None
    if settings.scheduler_enabled:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_scheduled_reminders, "interval", minutes=settings.scheduler_interval_minutes,
            id="appointment-reminders", max_instances=1, coalesce=True,
        )
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="ClinicConnect API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_origin_regex=get_settings().cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"
for r in (
    auth_router, memberships_router, admin_router, branches_router, services_router,
    appointments_router, patients_router, queue_router, notifications_router, inventory_router,
    reports_router, audit_router,
):
    app.include_router(r, prefix=PREFIX)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
