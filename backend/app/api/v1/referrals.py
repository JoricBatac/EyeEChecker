from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import clinic_user
from app.core.db import get_db
from app.core.errors import not_found
from app.modules.audit.service import audit
from app.modules.orgs.models import User
from app.modules.patients.models import Patient
from app.modules.referrals.models import Referral

router = APIRouter(prefix="/referrals", tags=["referrals"])

Status = Literal["to_refer", "referred", "seen", "closed"]


class ReferralPatch(BaseModel):
    status: Status | None = None
    notes: str | None = Field(default=None, max_length=2000)


def referral_out(r: Referral, p: Patient) -> dict:
    return {
        "id": r.id,
        "encounter_id": r.encounter_id,
        "patient": {"id": p.id, "full_name": p.full_name},
        "urgency": r.urgency,
        "reasons": r.reasons,
        "status": r.status,
        "notes": r.notes,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("")
def list_referrals(
    status: Status | None = None, user: User = Depends(clinic_user), db: Session = Depends(get_db)
) -> list[dict]:
    stmt = (
        select(Referral, Patient)
        .join(Patient, Patient.id == Referral.patient_id)
        .where(Referral.org_id == user.org_id)
    )
    if status:
        stmt = stmt.where(Referral.status == status)
    rows = db.execute(stmt.order_by(Referral.created_at.desc())).all()
    audit(db, user, "view", "referral_list", None, {"count": len(rows)})
    db.commit()
    order = {"urgent": 0, "soon": 1, "routine": 2}
    return sorted((referral_out(r, p) for r, p in rows), key=lambda x: order.get(x["urgency"], 3))


@router.patch("/{referral_id}")
def update_referral(
    referral_id: str, body: ReferralPatch, user: User = Depends(clinic_user), db: Session = Depends(get_db)
) -> dict:
    r = db.get(Referral, referral_id)
    if r is None or r.org_id != user.org_id:
        raise not_found("Referral not found")
    if body.status:
        r.status = body.status
    if body.notes is not None:
        r.notes = body.notes
    audit(db, user, "edit", "referral", r.id, {"status": r.status})
    db.commit()
    p = db.get(Patient, r.patient_id)
    assert p
    return referral_out(r, p)
