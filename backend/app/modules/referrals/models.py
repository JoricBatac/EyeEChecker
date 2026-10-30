from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Referral(IdMixin, TimestampMixin, Base):
    __tablename__ = "referrals"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    urgency: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="to_refer")  # to_refer | referred | seen | closed
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
