from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Patient(IdMixin, TimestampMixin, Base):
    __tablename__ = "patients"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id"))
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    age_years: Mapped[int | None] = mapped_column(Integer)  # used when birth date is unknown
    sex: Mapped[str | None] = mapped_column(String(10))
    contact: Mapped[str | None] = mapped_column(String(200))
    clinic_ref: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))

    def age_on(self, on: date) -> int | None:
        if self.birth_date:
            b = self.birth_date
            return on.year - b.year - ((on.month, on.day) < (b.month, b.day))
        return self.age_years


class Consent(IdMixin, Base):
    __tablename__ = "consents"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(50))  # care_documentation
    version: Mapped[str] = mapped_column(String(20))
    granted: Mapped[bool] = mapped_column(Boolean)
    recorded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
