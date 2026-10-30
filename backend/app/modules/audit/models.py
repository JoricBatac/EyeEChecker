from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, utcnow


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    org_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(50))  # view | create | edit | export | sign | delete | ...
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
