from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Report(IdMixin, TimestampMixin, Base):
    """Report text only. Photos are embedded in the PDF delivered at sign-off and never stored here."""

    __tablename__ = "reports"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))  # exam_note | referral_letter | patient_handout | addendum
    locale: Mapped[str] = mapped_column(String(5), default="en")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | signed
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="template")  # template | llm | edited
    parent_report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    signed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
