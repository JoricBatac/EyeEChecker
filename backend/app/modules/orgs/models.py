from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30), default="clinic")  # clinic | chain | program | internal
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    address: Mapped[str | None] = mapped_column(String(500))
    # Branding and feature settings, e.g. {"logo_key": ..., "llm_polish": false}
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class Site(IdMixin, TimestampMixin, Base):
    __tablename__ = "sites"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500))


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))
    profession: Mapped[str | None] = mapped_column(String(30))
    license_no: Mapped[str | None] = mapped_column(String(50))
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrgPack(Base):
    __tablename__ = "org_packs"
    __table_args__ = (UniqueConstraint("org_id", "pack_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    pack_id: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
