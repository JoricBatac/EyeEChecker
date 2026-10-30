"""Internal console (our team). De-identified, structured data only: no photos, names or free text (FR-4, FR-36)."""

import secrets
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import internal_admin, internal_user
from app.api.v1.auth import user_out
from app.core.db import get_db
from app.core.errors import conflict, not_found, unprocessable
from app.core.security import hash_password, subject_hash
from app.modules.audit.service import audit
from app.modules.encounters.models import ExamAnswers
from app.modules.monitoring.metrics import compute_metrics as _compute_metrics
from app.modules.monitoring.metrics import load_cases
from app.modules.orgs.models import Organization, OrgPack, User
from app.modules.packs.loader import CONDITION_STATES, get_pack, get_packs
from app.modules.packs.models import ConditionState
from app.modules.packs.states import resolve_condition_states
from app.modules.patients.models import Patient
from app.modules.review.models import ReviewNote

router = APIRouter(prefix="/internal", tags=["internal"])


class StateIn(BaseModel):
    state: Literal["off", "shadow", "reveal_after", "visible"]
    org_id: str | None = None
    model_version: str | None = None
    advisor_signoff: str | None = Field(default=None, max_length=1000)


class OrgIn(BaseModel):
    name: str
    kind: Literal["clinic", "chain", "program"] = "clinic"
    address: str | None = None
    admin_email: EmailStr
    admin_name: str


class PackEnableIn(BaseModel):
    enabled: bool


class ReviewNoteIn(BaseModel):
    verdict: Literal["ai_right", "clinician_right", "unclear"] | None = None
    note: str = Field(min_length=1, max_length=2000)


def _age_band(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age < 18:
        return "0-17"
    return f"{(age // 10) * 10}s" if age < 80 else "80+"


@router.get("/review-queue")
def review_queue(
    pack_id: str = "eye", user: User = Depends(internal_user), db: Session = Depends(get_db)
) -> list[dict]:
    pack = get_pack(pack_id)
    if pack is None:
        raise not_found()
    free_text = {f.id for f in (pack.exam_form.fields if pack.exam_form else []) if f.free_text}
    out = []
    for c in load_cases(db, pack_id):
        if c.top3_agrees:
            continue
        patient = db.get(Patient, c.encounter.patient_id)
        answers = db.get(ExamAnswers, c.encounter.id)
        notes = db.scalars(select(ReviewNote).where(ReviewNote.encounter_id == c.encounter.id)).all()
        out.append(
            {
                "case_id": c.encounter.id,
                "subject": subject_hash(c.encounter.patient_id),
                "age_band": _age_band(patient.age_on(date.today()) if patient else None),
                "sex": patient.sex if patient else None,
                "exam": {k: v for k, v in (answers.answers if answers else {}).items() if k not in free_text},
                "ai": {
                    "model_version": c.ai.model_version,
                    "probabilities": c.ai.probabilities,
                    "condition_states": c.ai.condition_states,
                },
                "clinician_pre_reveal": {
                    "diagnoses": [
                        {"condition_id": d["condition_id"], "side": d.get("side")} for d in c.pre.diagnoses
                    ],
                    "urgency": c.pre.urgency,
                },
                "clinician_final": {
                    "diagnoses": [d["condition_id"] for d in (c.post or c.pre).diagnoses],
                    "changed_after_reveal": bool(c.post and c.post.changed_after_reveal),
                },
                "review_notes": [
                    {"verdict": n.verdict, "note": n.note, "at": n.created_at.isoformat()} for n in notes
                ],
            }
        )
    audit(db, user, "view", "review_queue", None, {"count": len(out)})
    db.commit()
    return out


@router.post("/review-queue/{case_id}/notes")
def add_review_note(
    case_id: str, body: ReviewNoteIn, user: User = Depends(internal_user), db: Session = Depends(get_db)
) -> dict:
    note = ReviewNote(encounter_id=case_id, reviewer_id=user.id, verdict=body.verdict, note=body.note)
    db.add(note)
    audit(db, user, "create", "review_note", case_id)
    db.commit()
    return {"id": note.id}


@router.get("/metrics")
def metrics(pack_id: str = "eye", user: User = Depends(internal_user), db: Session = Depends(get_db)) -> dict:
    return _compute_metrics(db, pack_id)


@router.get("/packs")
def list_packs(user: User = Depends(internal_user)) -> list[dict]:
    return [
        {
            "id": p.id,
            "version": p.version,
            "name": p.name,
            "placeholder": p.placeholder,
            "model": p.model.model_dump(),
            "ruleset_version": p.ruleset.version if p.ruleset else None,
            "conditions": [{"id": c.id, "name": c.name, "emergency": c.emergency} for c in p.conditions],
        }
        for p in get_packs().values()
    ]


@router.get("/packs/{pack_id}/states")
def get_states(
    pack_id: str,
    org_id: str | None = None,
    model_version: str | None = None,
    user: User = Depends(internal_user),
    db: Session = Depends(get_db),
) -> dict:
    pack = get_pack(pack_id)
    if pack is None or pack.placeholder:
        raise not_found()
    version = model_version or pack.model.version
    return {
        "pack_id": pack_id,
        "org_id": org_id,
        "model_version": version,
        "states": resolve_condition_states(db, pack, org_id or "", version),
    }


@router.put("/packs/{pack_id}/conditions/{condition_id}/state")
def set_state(
    pack_id: str,
    condition_id: str,
    body: StateIn,
    user: User = Depends(internal_admin),
    db: Session = Depends(get_db),
) -> dict:
    pack = get_pack(pack_id)
    if pack is None or pack.placeholder:
        raise not_found("Pack not found")
    if condition_id not in pack.classifiable_ids:
        raise not_found("Condition not found")
    if body.state == "visible" and not body.advisor_signoff:
        raise unprocessable(
            "Moving a condition to visible requires the clinical advisor's sign-off (PRD 10.3)"
        )
    assert body.state in CONDITION_STATES
    row = db.scalar(
        select(ConditionState).where(
            ConditionState.pack_id == pack_id,
            ConditionState.condition_id == condition_id,
            ConditionState.org_id.is_(None) if body.org_id is None else ConditionState.org_id == body.org_id,
            ConditionState.model_version.is_(None)
            if body.model_version is None
            else ConditionState.model_version == body.model_version,
        )
    )
    if row is None:
        row = ConditionState(
            pack_id=pack_id,
            condition_id=condition_id,
            org_id=body.org_id,
            model_version=body.model_version,
            state="",
        )
        db.add(row)
    row.state, row.advisor_signoff, row.set_by = body.state, body.advisor_signoff, user.id
    audit(
        db,
        user,
        "edit",
        "condition_state",
        None,
        {"pack": pack_id, "condition": condition_id, **body.model_dump()},
    )
    db.commit()
    return {"pack_id": pack_id, "condition_id": condition_id, **body.model_dump()}


@router.get("/orgs")
def list_orgs(user: User = Depends(internal_user), db: Session = Depends(get_db)) -> list[dict]:
    orgs = db.scalars(select(Organization).where(Organization.is_internal.is_(False))).all()
    out = []
    for o in orgs:
        packs = db.scalars(select(OrgPack).where(OrgPack.org_id == o.id, OrgPack.enabled.is_(True))).all()
        out.append({"id": o.id, "name": o.name, "kind": o.kind, "packs": [p.pack_id for p in packs]})
    return out


@router.post("/orgs")
def create_org(body: OrgIn, user: User = Depends(internal_admin), db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(User).where(User.email == body.admin_email.lower())):
        raise conflict("Admin email already registered")
    org = Organization(name=body.name, kind=body.kind, address=body.address)
    db.add(org)
    db.flush()
    temp_password = secrets.token_urlsafe(12)
    admin = User(
        org_id=org.id,
        email=body.admin_email.lower(),
        full_name=body.admin_name,
        role="org_admin",
        password_hash=hash_password(temp_password),
    )
    db.add(admin)
    audit(db, user, "create", "organization", org.id)
    db.commit()
    return {"id": org.id, "name": org.name, "admin": {**user_out(admin), "temporary_password": temp_password}}


@router.put("/orgs/{org_id}/packs/{pack_id}")
def enable_pack(
    org_id: str,
    pack_id: str,
    body: PackEnableIn,
    user: User = Depends(internal_admin),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, org_id)
    pack = get_pack(pack_id)
    if org is None or pack is None:
        raise not_found()
    if body.enabled and pack.placeholder:
        raise conflict(f"Pack {pack_id} is a placeholder and cannot be enabled")
    row = db.scalar(select(OrgPack).where(OrgPack.org_id == org_id, OrgPack.pack_id == pack_id))
    if row is None:
        row = OrgPack(org_id=org_id, pack_id=pack_id, enabled=body.enabled)
        db.add(row)
    row.enabled = body.enabled
    audit(db, user, "edit", "org_pack", org_id, {"pack": pack_id, "enabled": body.enabled})
    db.commit()
    return {"org_id": org_id, "pack_id": pack_id, "enabled": row.enabled}
