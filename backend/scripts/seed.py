"""Create demo organizations and users for local development.

    python -m scripts.seed            (from backend/)

Prints the logins. Never run against production.
"""

from sqlalchemy import select

from app import models  # noqa: F401
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.security import hash_password
from app.modules.orgs.models import Organization, OrgPack, Site, User

PASSWORD = "scanassist-dev"


def run() -> None:
    if get_settings().is_production:
        raise SystemExit("Refusing to seed a production database")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "clinician@demo.ph")):
            print("Already seeded.")
            return
        internal = Organization(name="ScanAssist (internal)", kind="internal", is_internal=True)
        clinic = Organization(name="Demo Eye Clinic", kind="clinic", address="123 Rizal Ave, Manila")
        db.add_all([internal, clinic])
        db.flush()
        db.add(Site(org_id=clinic.id, name="Main", address=clinic.address))
        db.add(OrgPack(org_id=clinic.id, pack_id="eye", enabled=True))
        users = [
            (internal, "admin@scanassist.dev", "Internal Admin", "internal_admin", None, None),
            (
                internal,
                "reviewer@scanassist.dev",
                "Clinical Reviewer",
                "internal_reviewer",
                "ophthalmologist",
                None,
            ),
            (clinic, "clinician@demo.ph", "Dr. Maria Santos", "clinician", "physician", "0123456"),
            (clinic, "optom@demo.ph", "Dr. Jose Reyes", "clinician", "optometrist", "OD-98765"),
            (clinic, "staff@demo.ph", "Ana Cruz", "staff", "nurse", None),
            (clinic, "owner@demo.ph", "Clinic Owner", "org_admin", None, None),
        ]
        for org, email, name, role, profession, lic in users:
            db.add(
                User(
                    org_id=org.id,
                    email=email,
                    full_name=name,
                    role=role,
                    profession=profession,
                    license_no=lic,
                    password_hash=hash_password(PASSWORD),
                )
            )
        db.commit()
    print(f"Seeded. Password for every account: {PASSWORD}")
    for _, email, _, role, *_ in users:
        print(f"  {role:18} {email}")
    print("Admin roles enroll MFA (TOTP) on first login.")


if __name__ == "__main__":
    run()
