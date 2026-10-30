from typing import Any

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


def audit(
    db: Session,
    user: Any | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    detail: dict | None = None,
    org_id: str | None = None,
) -> None:
    """Record an access or change. Added to the caller's transaction; commit happens with the change itself."""
    db.add(
        AuditLog(
            user_id=getattr(user, "id", None),
            org_id=org_id or getattr(user, "org_id", None),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail or {},
        )
    )
