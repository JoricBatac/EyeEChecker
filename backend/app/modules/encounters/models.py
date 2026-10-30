from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Encounter(IdMixin, TimestampMixin, Base):
    __tablename__ = "encounters"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    pack_id: Mapped[str] = mapped_column(String(50))
    pack_version: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | signed | expired
    signed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    photos_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Photo(IdMixin, TimestampMixin, Base):
    """Temporary photo reference. The image itself lives only in object storage, never in the database."""

    __tablename__ = "photos"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    view: Mapped[str] = mapped_column(String(50))
    storage_key: Mapped[str] = mapped_column(String(300))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default="camera")  # camera | upload
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_override_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExamAnswers(Base):
    __tablename__ = "exam_answers"

    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), primary_key=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AIResult(IdMixin, TimestampMixin, Base):
    """Full model output. Never serialized directly to clinic users; see inference.visibility."""

    __tablename__ = "ai_results"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(100))
    classifier_kind: Mapped[str] = mapped_column(String(30))
    probabilities: Mapped[dict] = mapped_column(JSON)
    condition_states: Mapped[dict] = mapped_column(JSON)  # state of each condition at time of run
    shown_conditions: Mapped[list] = mapped_column(JSON, default=list)  # visible before assessment
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RedFlagAlert(IdMixin, TimestampMixin, Base):
    __tablename__ = "red_flag_alerts"
    __table_args__ = (UniqueConstraint("encounter_id", "rule_id", "subject"),)

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(80))
    subject: Mapped[str] = mapped_column(String(80), default="")  # e.g. condition for model-based alerts
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))  # rules | model
    shown: Mapped[bool] = mapped_column(Boolean, default=True)
    referral: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(IdMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    ai_result_id: Mapped[str] = mapped_column(ForeignKey("ai_results.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[str] = mapped_column(String(30))  # correct | wrong_cause | wrong_urgency | not_useful
