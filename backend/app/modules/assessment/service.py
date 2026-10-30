from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import unprocessable
from app.modules.assessment.models import Assessment
from app.modules.audit.service import audit
from app.modules.encounters import service as enc_service
from app.modules.encounters.models import AIResult, Encounter
from app.modules.orgs.models import User
from app.modules.packs.loader import Pack


class DiagnosisIn(BaseModel):
    condition_id: str
    side: Literal["right", "left", "both"] | None = None
    note: str | None = Field(default=None, max_length=1000)


class PlanIn(BaseModel):
    items: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    refer: bool = False


class AssessmentIn(BaseModel):
    diagnoses: list[DiagnosisIn] = Field(min_length=1)
    urgency: Literal["routine", "soon", "urgent"]
    plan: PlanIn = Field(default_factory=PlanIn)


def _validate(pack: Pack, user: User, body: AssessmentIn) -> None:
    errors = []
    ids = [d.condition_id for d in body.diagnoses]
    errors += [f"unknown condition {cid}" for cid in ids if pack.condition(cid) is None]
    if len(ids) != len(set(ids)):
        errors.append("duplicate diagnosis")
    for item in body.plan.items:
        option = pack.management_option(item, ids)
        if option is None:
            errors.append(f"unknown management option {item}")
        elif user.profession not in option.professions:
            errors.append(f"management option {item} is outside your scope of practice")
    if errors:
        raise unprocessable(errors)


def agreement(ai: AIResult | None, diagnoses: list[str]) -> str:
    """Agreement with the suggestion the clinician actually saw before deciding (FR-26)."""
    if ai is None or not ai.shown_conditions:
        return "not_shown"
    shown = list(ai.shown_conditions)
    if diagnoses[0] == shown[0]:
        return "agreed"
    if set(diagnoses) & set(shown):
        return "edited"
    return "rejected"


def save_assessment(db: Session, user: User, enc: Encounter, body: AssessmentIn) -> Assessment:
    """First save is the immutable pre-reveal assessment; later saves are stored as post_reveal."""
    enc_service.require_draft(enc)
    pack = enc_service.pack_for(enc)
    _validate(pack, user, body)
    existing = enc_service.assessments(db, enc)
    ai = enc_service.latest_ai(db, enc)
    dx_ids = [d.condition_id for d in body.diagnoses]
    data = dict(
        diagnoses=[d.model_dump() for d in body.diagnoses],
        urgency=body.urgency,
        plan=body.plan.model_dump(),
        clinician_id=user.id,
    )

    if "pre_reveal" not in existing:
        a = Assessment(
            org_id=enc.org_id,
            encounter_id=enc.id,
            phase="pre_reveal",
            agreement=agreement(ai, dx_ids),
            **data,
        )
        db.add(a)
    else:
        pre = existing["pre_reveal"]
        a = existing.get("post_reveal") or Assessment(
            org_id=enc.org_id, encounter_id=enc.id, phase="post_reveal"
        )
        for k, v in data.items():
            setattr(a, k, v)
        a.agreement = pre.agreement
        a.changed_after_reveal = bool(ai and ai.revealed_at) and (
            [d["condition_id"] for d in pre.diagnoses] != dx_ids or pre.urgency != body.urgency
        )
        a.created_at = utcnow()
        db.add(a)
    db.flush()
    enc_service.retriage(db, enc)  # diagnoses can trigger rules (e.g. pediatric reflex) and conditional views
    audit(db, user, "edit", "assessment", enc.id, {"phase": a.phase})
    db.commit()
    return a


def assessment_out(a: Assessment | None) -> dict | None:
    if a is None:
        return None
    return {
        "id": a.id,
        "phase": a.phase,
        "diagnoses": a.diagnoses,
        "urgency": a.urgency,
        "plan": a.plan,
        "agreement": a.agreement,
        "changed_after_reveal": a.changed_after_reveal,
        "created_at": a.created_at.isoformat(),
    }
