import hashlib
import hmac
from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.db import utcnow


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(subject: str, purpose: str, minutes: int, extra: dict[str, Any] | None = None) -> str:
    now = utcnow()
    payload = {"sub": subject, "purpose": purpose, "iat": now, "exp": now + timedelta(minutes=minutes)}
    payload.update(extra or {})
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def decode_token(token: str, purpose: str) -> dict[str, Any]:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("purpose") != purpose:
        raise jwt.InvalidTokenError("wrong token purpose")
    return payload


def subject_hash(patient_id: str) -> str:
    """Salted hash that replaces patient IDs in internal, de-identified views."""
    salt = get_settings().patient_hash_salt.encode()
    return hmac.new(salt, patient_id.encode(), hashlib.sha256).hexdigest()[:16]
