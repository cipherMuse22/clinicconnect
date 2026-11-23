"""Sending notifications (FR-041 to FR-045).

Each channel is a provider. In the prototype only "in_app" is real: the stored row IS the notification
the patient sees. "sms" and "email" are simulated (they log what they would send). To add a real
provider (NFR-023), write a class with `channel` and `send(patient, message)` and call `register_provider`.
"""
import logging
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.accounts.models import Patient
from app.modules.notifications.models import Notification

log = logging.getLogger("clinicconnect.notifications")


class NotificationProvider(Protocol):
    channel: str

    def send(self, patient: Patient, message: str) -> bool: ...


class InAppProvider:
    channel = "in_app"

    def send(self, patient: Patient, message: str) -> bool:
        return True  # nothing to deliver: the app reads the stored row


class SimulatedProvider:
    """Stands in for a real SMS or email gateway. Logs only the patient id, never contact details or text."""

    def __init__(self, channel: str):
        self.channel = channel

    def send(self, patient: Patient, message: str) -> bool:
        log.info("[simulated %s] would notify patient %s", self.channel, patient.patient_id)
        return True


PROVIDERS: dict[str, NotificationProvider] = {
    p.channel: p for p in (InAppProvider(), SimulatedProvider("sms"), SimulatedProvider("email"))
}


def register_provider(provider: NotificationProvider) -> None:
    PROVIDERS[provider.channel] = provider


def notify(
    db: Session, patient_id: int, notification_type: str, message: str, appointment_id: int | None = None
) -> list[Notification]:
    """Record and send a notification on every configured channel. Added to the caller's transaction,
    so a booking and its notification are saved together or not at all. A failing provider never
    blocks the booking: that channel is just recorded as failed."""
    patient = db.get(Patient, patient_id)
    rows = []
    for channel in get_settings().notification_channels:
        provider = PROVIDERS.get(channel)
        if provider is None:
            continue
        try:
            ok = provider.send(patient, message)
        except Exception:  # noqa: BLE001
            log.exception("notification provider %s failed", channel)
            ok = False
        row = Notification(
            patient_id=patient_id,
            appointment_id=appointment_id,
            notification_type=notification_type,
            message=message[:500],
            channel=channel,
            status="sent" if ok else "failed",
            sent_at=datetime.now().astimezone(),
        )
        db.add(row)
        rows.append(row)
    return rows
