from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import forbidden
from app.core.security import decode_token
from app.modules.auth.roles import CLINIC_ROLES, INTERNAL_ROLES, Role
from app.modules.orgs.models import User

bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if creds is None:
        raise unauthorized
    try:
        payload = decode_token(creds.credentials, "access")
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = {r.value for r in roles}

    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise forbidden()
        return user

    return dep


# Internal roles never reach clinic endpoints (they see de-identified data only, FR-4).
clinic_user = require_roles(*CLINIC_ROLES)
clinician = require_roles(Role.clinician)
org_admin = require_roles(Role.org_admin)
internal_user = require_roles(*INTERNAL_ROLES)
internal_admin = require_roles(Role.internal_admin)
