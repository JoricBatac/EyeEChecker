"""Clinic organization settings and user management (org_admin)."""

import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import clinic_user, org_admin
from app.api.v1.auth import user_out
from app.core.db import get_db
from app.core.errors import conflict, not_found, unprocessable
from app.core.security import hash_password
from app.modules.audit.service import audit
from app.modules.auth.roles import CLINIC_ROLES, Profession, Role
from app.modules.orgs.models import Organization, Site, User

router = APIRouter(prefix="/org", tags=["org"])


class OrgSettingsIn(BaseModel):
    name: str | None = None
    address: str | None = None
    llm_polish: bool | None = None


class UserIn(BaseModel):
    email: EmailStr
    full_name: str
    role: Role
    profession: Profession | None = None
    license_no: str | None = None


class UserPatch(BaseModel):
    is_active: bool | None = None
    license_no: str | None = None


class SiteIn(BaseModel):
    name: str
    address: str | None = None


def org_out(org: Organization, sites: list[Site]) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "kind": org.kind,
        "address": org.address,
        "settings": org.settings,
        "sites": [{"id": s.id, "name": s.name, "address": s.address} for s in sites],
    }


@router.get("")
def get_org(user: User = Depends(clinic_user), db: Session = Depends(get_db)) -> dict:
    org = db.get(Organization, user.org_id)
    sites = db.scalars(select(Site).where(Site.org_id == user.org_id)).all()
    return org_out(org, list(sites))  # type: ignore[arg-type]


@router.put("/settings")
def update_settings(
    body: OrgSettingsIn, user: User = Depends(org_admin), db: Session = Depends(get_db)
) -> dict:
    org = db.get(Organization, user.org_id)
    assert org
    if body.name:
        org.name = body.name
    if body.address is not None:
        org.address = body.address
    if body.llm_polish is not None:
        org.settings = {**org.settings, "llm_polish": body.llm_polish}
    audit(db, user, "edit", "organization", org.id)
    db.commit()
    return get_org(user, db)


@router.post("/sites")
def add_site(body: SiteIn, user: User = Depends(org_admin), db: Session = Depends(get_db)) -> dict:
    site = Site(org_id=user.org_id, name=body.name, address=body.address)
    db.add(site)
    audit(db, user, "create", "site", site.id)
    db.commit()
    return {"id": site.id, "name": site.name, "address": site.address}


@router.get("/users")
def list_users(user: User = Depends(org_admin), db: Session = Depends(get_db)) -> list[dict]:
    users = db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.full_name)).all()
    return [{**user_out(u), "is_active": u.is_active} for u in users]


@router.post("/users")
def invite_user(body: UserIn, user: User = Depends(org_admin), db: Session = Depends(get_db)) -> dict:
    if body.role not in CLINIC_ROLES:
        raise unprocessable("Clinic admins can only create clinic roles")
    if body.role == Role.clinician and not body.profession:
        raise unprocessable("Clinicians need a profession")
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise conflict("Email already registered")
    temp_password = secrets.token_urlsafe(12)
    new = User(
        org_id=user.org_id,
        email=body.email.lower(),
        full_name=body.full_name,
        role=body.role.value,
        profession=body.profession.value if body.profession else None,
        license_no=body.license_no,
        password_hash=hash_password(temp_password),
    )
    db.add(new)
    audit(db, user, "create", "user", new.id, {"role": new.role})
    db.commit()
    # Shown once to the admin to pass on; email delivery comes later.
    return {**user_out(new), "temporary_password": temp_password}


@router.patch("/users/{user_id}")
def update_user(
    user_id: str, body: UserPatch, user: User = Depends(org_admin), db: Session = Depends(get_db)
) -> dict:
    target = db.get(User, user_id)
    if target is None or target.org_id != user.org_id:
        raise not_found()
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.license_no is not None:
        target.license_no = body.license_no
    audit(db, user, "edit", "user", target.id, body.model_dump(exclude_none=True))
    db.commit()
    return {**user_out(target), "is_active": target.is_active}
