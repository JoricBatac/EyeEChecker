from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Assessment(IdMixin, TimestampMixin, Base):
    """Clinician assessment.

    `pre_reveal` is the first assessment and is immutable: it records the clinician's independent judgment.
    Any later change (including after "Compare with AI") is stored as `post_reveal`.
    """

    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("encounter_id", "phase"),)

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    clinician_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    phase: Mapped[str] = mapped_column(String(20))  # pre_reveal | post_reveal
    # [{"condition_id": str, "side": "right|left|both|null", "note": str|null}]
    diagnoses: Mapped[list] = mapped_column(JSON)
    urgency: Mapped[str] = mapped_column(String(20))  # routine | soon | urgent
    # {"items": [management option ids], "notes": str|null, "refer": bool}
    plan: Mapped[dict] = mapped_column(JSON)
    agreement: Mapped[str] = mapped_column(String(20))  # agreed | edited | rejected | not_shown
    changed_after_reveal: Mapped[bool | None] = mapped_column(default=None)
