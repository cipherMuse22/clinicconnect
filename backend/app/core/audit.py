import json

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


def write_audit(
    db: Session,
    *,
    actor_staff_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Add an audit row to the current transaction. Never put passwords or tokens in details."""
    db.add(
        AuditLog(
            actor_staff_id=actor_staff_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
        )
    )
