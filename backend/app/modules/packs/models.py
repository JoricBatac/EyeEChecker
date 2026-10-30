from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, utcnow


class ConditionState(IdMixin, Base):
    """Per-condition AI enablement: off | shadow | reveal_after | visible (PRD 10.3).

    org_id and model_version are optional scopes; the most specific row wins.
    """

    __tablename__ = "condition_states"

    pack_id: Mapped[str] = mapped_column(String(50), index=True)
    condition_id: Mapped[str] = mapped_column(String(80))
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"))
    model_version: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(20))
    advisor_signoff: Mapped[str | None] = mapped_column(Text)
    set_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
