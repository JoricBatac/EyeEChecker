from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class ReviewNote(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_notes"

    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str | None] = mapped_column(String(30))  # ai_right | clinician_right | unclear
    note: Mapped[str] = mapped_column(Text)
