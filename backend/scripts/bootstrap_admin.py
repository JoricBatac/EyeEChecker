"""Create the first internal admin on a fresh production database. Prints a one-time password.

python -c "from scripts.bootstrap_admin import run; run('you@domain', 'Your Name')"
"""

import secrets

from sqlalchemy import select

from app import models  # noqa: F401
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.orgs.models import Organization, User


def run(email: str, full_name: str) -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.role == "internal_admin")):
            raise SystemExit("An internal admin already exists")
        org = db.scalar(select(Organization).where(Organization.is_internal.is_(True)))
        if org is None:
            org = Organization(name="ScanAssist (internal)", kind="internal", is_internal=True)
            db.add(org)
            db.flush()
        password = secrets.token_urlsafe(16)
        db.add(
            User(
                org_id=org.id,
                email=email.lower(),
                full_name=full_name,
                role="internal_admin",
                password_hash=hash_password(password),
            )
        )
        db.commit()
    print(f"Created {email}. One-time password: {password}  (MFA enrollment on first login)")
