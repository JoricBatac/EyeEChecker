import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_token, decode_token, verify_password
from app.modules.audit.service import audit
from app.modules.auth.roles import MFA_ROLES
from app.modules.orgs.models import Organization, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MfaIn(BaseModel):
    mfa_token: str
    code: str


def user_out(user: User, org: Organization | None = None) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "profession": user.profession,
        "license_no": user.license_no,
        "org_id": user.org_id,
        "org_name": org.name if org else None,
    }


def _access(db: Session, user: User) -> dict:
    s = get_settings()
    token = create_token(user.id, "access", s.access_token_minutes, {"role": user.role, "org": user.org_id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_out(user, db.get(Organization, user.org_id)),
    }


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user.role in MFA_ROLES:
        out: dict = {
            "mfa_required": True,
            "mfa_token": create_token(user.id, "mfa", get_settings().mfa_token_minutes),
        }
        if not user.mfa_enrolled:
            if not user.mfa_secret:
                user.mfa_secret = pyotp.random_base32()
                db.commit()
            out["enrollment"] = {
                "secret": user.mfa_secret,
                "otpauth_uri": pyotp.TOTP(user.mfa_secret).provisioning_uri(
                    user.email, issuer_name="ScanAssist"
                ),
            }
        return out
    audit(db, user, "login", "user", user.id)
    db.commit()
    return _access(db, user)


@router.post("/mfa")
def mfa(body: MfaIn, db: Session = Depends(get_db)) -> dict:
    try:
        payload = decode_token(body.mfa_token, "mfa")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA session expired, log in again") from None
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active or not user.mfa_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA session")
    if not pyotp.TOTP(user.mfa_secret).verify(body.code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code")
    user.mfa_enrolled = True
    audit(db, user, "login", "user", user.id, {"mfa": True})
    db.commit()
    return _access(db, user)


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_out(user, db.get(Organization, user.org_id))
