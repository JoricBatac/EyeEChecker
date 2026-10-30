from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import clinic_user, clinician
from app.api.v1.patients import get_patient_for, has_care_consent, patient_out
from app.core.db import get_db
from app.core.errors import conflict, not_found, unprocessable
from app.core.storage import Storage, get_storage
from app.modules.assessment.service import AssessmentIn, assessment_out, save_assessment
from app.modules.audit.service import audit
from app.modules.encounters import service as svc
from app.modules.encounters.models import Encounter, Feedback, Photo
from app.modules.inference import visibility
from app.modules.orgs.models import User
from app.modules.packs.loader import get_pack, missing_required
from app.modules.packs.states import enabled_pack_ids
from app.modules.patients.models import Consent, Patient
from app.modules.reports import service as reports
from app.modules.reports.models import Report

router = APIRouter(prefix="/encounters", tags=["encounters"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class EncounterIn(BaseModel):
    patient_id: str
    pack_id: str


class ExamIn(BaseModel):
    answers: dict[str, Any]


class PhotoPatch(BaseModel):
    quality_override_reason: str = Field(min_length=3, max_length=500)


class ReportIn(BaseModel):
    type: Literal["exam_note", "referral_letter", "patient_handout"]
    locale: Literal["en", "fil"] = "en"


class SignOffIn(BaseModel):
    report_ids: list[str] = Field(min_length=1)


class FeedbackIn(BaseModel):
    rating: Literal["correct", "wrong_cause", "wrong_urgency", "not_useful"]


def encounter_out(db: Session, storage: Storage, enc: Encounter) -> dict:
    pack = svc.pack_for(enc)
    patient = db.get(Patient, enc.patient_id)
    assert patient
    ai = svc.latest_ai(db, enc)
    phases = svc.assessments(db, enc)
    all_reports = db.scalars(
        select(Report).where(Report.encounter_id == enc.id).order_by(Report.created_at)
    ).all()
    return {
        "id": enc.id,
        "pack_id": enc.pack_id,
        "pack_version": enc.pack_version,
        "status": enc.status,
        "created_at": enc.created_at.isoformat(),
        "signed_at": enc.signed_at.isoformat() if enc.signed_at else None,
        "photos_deleted": enc.photos_deleted_at is not None,
        "patient": patient_out(patient),
        "photos": [svc.photo_out(storage, p) for p in svc.active_photos(db, enc)],
        "exam": svc.answers_for(db, enc),
        "red_flags": [svc.alert_out(a) for a in svc.shown_alerts(db, enc)],
        "ai": {
            "available": ai is not None,
            "suggestions": visibility.suggestions(pack, ai, visibility.BEFORE_ASSESSMENT) if ai else [],
            "revealed": bool(ai and ai.revealed_at),
            **(visibility.label(ai) if ai else {}),
        },
        "assessment": assessment_out(phases.get("post_reveal") or phases.get("pre_reveal")),
        "pre_reveal_assessment": assessment_out(phases.get("pre_reveal")),
        "reports": [reports.report_out(r) for r in all_reports],
        "required_views": svc.required_views(db, enc) if enc.status == "draft" else [],
        "missing_fields": missing_required(pack, svc.facts_for(db, enc, include_model=False)),
    }


@router.post("")
def create_encounter(
    body: EncounterIn,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    patient = get_patient_for(db, user, body.patient_id)
    if body.pack_id not in enabled_pack_ids(db, user.org_id):
        raise not_found("Pack not enabled for your organization")
    consents = db.scalars(select(Consent).where(Consent.patient_id == patient.id)).all()
    if not has_care_consent(list(consents)):
        raise conflict("Record the patient's consent before starting an encounter")
    pack = get_pack(body.pack_id)
    assert pack
    enc = Encounter(
        org_id=user.org_id,
        patient_id=patient.id,
        pack_id=pack.id,
        pack_version=pack.version,
        created_by=user.id,
    )
    db.add(enc)
    db.flush()
    audit(db, user, "create", "encounter", enc.id)
    db.commit()
    return encounter_out(db, storage, enc)


@router.get("")
def list_encounters(
    status: str | None = None,
    limit: int = 50,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(Encounter, Patient)
        .join(Patient, Patient.id == Encounter.patient_id)
        .where(Encounter.org_id == user.org_id)
    )
    if status:
        stmt = stmt.where(Encounter.status == status)
    rows = db.execute(stmt.order_by(Encounter.created_at.desc()).limit(min(limit, 200))).all()
    audit(db, user, "view", "encounter_list", None, {"count": len(rows)})
    db.commit()
    return [
        {
            "id": e.id,
            "pack_id": e.pack_id,
            "status": e.status,
            "created_at": e.created_at.isoformat(),
            "patient": {"id": p.id, "full_name": p.full_name},
        }
        for e, p in rows
    ]


@router.get("/{encounter_id}")
def get_encounter(
    encounter_id: str,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    audit(db, user, "view", "encounter", enc.id)
    db.commit()
    return encounter_out(db, storage, enc)


@router.post("/{encounter_id}/photos")
async def upload_photo(
    encounter_id: str,
    view: str = Form(...),
    source: Literal["camera", "upload"] = Form("camera"),
    file: UploadFile = File(...),
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise unprocessable("Photo is larger than 15 MB")
    photo = svc.add_photo(db, storage, user, enc, view, data, source)
    return svc.photo_out(storage, photo)


@router.patch("/{encounter_id}/photos/{photo_id}")
def override_quality(
    encounter_id: str,
    photo_id: str,
    body: PhotoPatch,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    photo = db.get(Photo, photo_id)
    if photo is None or photo.encounter_id != enc.id or photo.deleted_at:
        raise not_found("Photo not found")
    photo.quality_override_reason = body.quality_override_reason
    audit(db, user, "edit", "photo", photo.id, {"quality_override": True})
    db.commit()
    return svc.photo_out(storage, photo)


@router.delete("/{encounter_id}/photos/{photo_id}")
def delete_photo(
    encounter_id: str,
    photo_id: str,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    svc.require_draft(enc)
    photo = db.get(Photo, photo_id)
    if photo is None or photo.encounter_id != enc.id or photo.deleted_at:
        raise not_found("Photo not found")
    storage.delete(photo.storage_key)
    photo.deleted_at = svc.utcnow()
    audit(db, user, "delete", "photo", photo.id, {"reason": "retake"})
    db.commit()
    return {"deleted": True}


@router.put("/{encounter_id}/exam")
def save_exam(
    encounter_id: str, body: ExamIn, user: User = Depends(clinic_user), db: Session = Depends(get_db)
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    answers = svc.save_exam(db, user, enc, body.answers)
    pack = svc.pack_for(enc)
    return {
        "answers": answers,
        "red_flags": [svc.alert_out(a) for a in svc.shown_alerts(db, enc)],
        "missing_fields": missing_required(pack, svc.facts_for(db, enc, include_model=False)),
        "required_views": svc.required_views(db, enc),
    }


@router.post("/{encounter_id}/analyze")
def analyze(
    encounter_id: str,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    return svc.analyze(db, storage, user, enc)


@router.get("/{encounter_id}/ai-compare")
def ai_compare(encounter_id: str, user: User = Depends(clinician), db: Session = Depends(get_db)) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    return svc.ai_compare(db, user, enc)


@router.post("/{encounter_id}/alerts/{alert_id}/ack")
def acknowledge(
    encounter_id: str, alert_id: str, user: User = Depends(clinician), db: Session = Depends(get_db)
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    return svc.acknowledge_alert(db, user, enc, alert_id)


@router.put("/{encounter_id}/assessment")
def put_assessment(
    encounter_id: str, body: AssessmentIn, user: User = Depends(clinician), db: Session = Depends(get_db)
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    a = save_assessment(db, user, enc, body)
    ai = svc.latest_ai(db, enc)
    return {
        "assessment": assessment_out(a),
        "red_flags": [svc.alert_out(x) for x in svc.shown_alerts(db, enc)],
        "compare_available": bool(ai and visibility.allowed_conditions(ai, visibility.AFTER_ASSESSMENT)),
        "required_views": svc.required_views(db, enc),
    }


@router.post("/{encounter_id}/reports")
def draft_report(
    encounter_id: str, body: ReportIn, user: User = Depends(clinic_user), db: Session = Depends(get_db)
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    if enc.status == "expired":
        raise conflict("Encounter expired")
    return reports.report_out(reports.draft_report(db, user, enc, body.type, body.locale))


@router.post("/{encounter_id}/sign-off")
def sign_off(
    encounter_id: str,
    body: SignOffIn,
    user: User = Depends(clinician),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    return reports.sign_off(db, storage, user, enc, body.report_ids)


@router.post("/{encounter_id}/feedback")
def feedback(
    encounter_id: str, body: FeedbackIn, user: User = Depends(clinician), db: Session = Depends(get_db)
) -> dict:
    enc = svc.get_encounter_for(db, user, encounter_id)
    ai = svc.latest_ai(db, enc)
    if ai is None or not (ai.shown_conditions or ai.revealed_at):
        raise conflict("No AI suggestion was shown for this encounter")
    db.add(
        Feedback(
            org_id=enc.org_id, encounter_id=enc.id, ai_result_id=ai.id, user_id=user.id, rating=body.rating
        )
    )
    db.commit()
    return {"ok": True}
