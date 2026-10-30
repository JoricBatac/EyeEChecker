"""Create a clinic access code for a design partner. The code is shown once; only its hash is stored.

python -m scripts.create_access_code "Demo Eye Clinic"
python -m scripts.create_access_code --revoke ABCD-EFGH-JKLM
"""

import argparse

from sqlalchemy import select

from app import models  # noqa: F401
from app.core.db import Base, SessionLocal, engine
from app.modules.assist.models import AccessCode
from app.modules.assist.service import hash_code, new_code


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="?", help="design partner name")
    ap.add_argument("--revoke", metavar="CODE")
    args = ap.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if args.revoke:
            row = db.scalar(select(AccessCode).where(AccessCode.code_hash == hash_code(args.revoke)))
            if row is None:
                raise SystemExit("Code not found")
            row.active = False
            db.commit()
            print(f"Revoked code for {row.label}")
            return
        if not args.label:
            ap.error("label is required")
        code = new_code()
        db.add(AccessCode(label=args.label, code_hash=hash_code(code)))
        db.commit()
    print(f"Access code for {args.label}: {code}")
    print("Share it with the clinic privately. It cannot be shown again.")


if __name__ == "__main__":
    main()
