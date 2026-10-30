"""Stateless assist mode: the only rows are clinic access codes and anonymous score logs.

No photos, names, contact details, exam free text or patient IDs are ever stored.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, utcnow


class AccessCode(IdMixin, Base):
    __tablename__ = "access_codes"

    label: Mapped[str] = mapped_column(String(200))  # design partner name
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_on: Mapped[date | None] = mapped_column(Date)


class AssistScore(IdMixin, Base):
    """AI output next to the clinician's own call, for per-condition agreement metrics (PRD 10.3)."""

    __tablename__ = "assist_scores"

    analysis_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    created_on: Mapped[date] = mapped_column(Date, default=lambda: utcnow().date())  # day only
    access_code_id: Mapped[str] = mapped_column(ForeignKey("access_codes.id"), index=True)
    pack_id: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str] = mapped_column(String(100))
    probabilities: Mapped[dict] = mapped_column(JSON)
    condition_states: Mapped[dict] = mapped_column(JSON)
    age_band: Mapped[str] = mapped_column(String(10))
    red_flags: Mapped[list] = mapped_column(JSON, default=list)  # rule ids only
    clinician_dx: Mapped[list] = mapped_column(JSON)  # condition ids, before seeing the AI
    clinician_urgency: Mapped[str] = mapped_column(String(20))
    final_dx: Mapped[list | None] = mapped_column(JSON)
    changed_after_reveal: Mapped[bool | None] = mapped_column(Boolean)
    rating: Mapped[str | None] = mapped_column(String(30))
    # reveal_after_pick: clinician_dx recorded before seeing the AI (independent).
    # quick: AI shown first, clinician_dx is a confirmation (anchored; analyze separately).
    mode: Mapped[str] = mapped_column(String(20), default="reveal_after_pick")
