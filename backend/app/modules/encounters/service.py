from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from PIL import Image
from scanassist_core.preprocess import load_rgb, sanitize_photo
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import expr
from app.core.config import get_settings
from app.core.db import as_utc, utcnow
from app.core.errors import conflict, not_found, unprocessable
from app.core.storage import Storage, photo_key
from app.modules.assessment.models import Assessment
from app.modules.audit.service import audit
from app.modules.encounters.models import AIResult, Encounter, ExamAnswers, Photo, RedFlagAlert
from app.modules.inference import visibility
from app.modules.inference.classifiers import get_classifier
from app.modules.orgs.models import User
from app.modules.packs.loader import Pack, get_pack, missing_required, validate_answers
from app.modules.packs.states import resolve_condition_states
from app.modules.patients.models import Patient
from app.modules.quality.checks import check_quality
from app.modules.reports.models import Report
from app.modules.triage.engine import TriageResult, build_facts, max_urgency, run_triage

log = logging.getLogger(__name__)


# ---------- lookups ----------


def get_encounter_for(db: Session, user: User, encounter_id: str) -> Encounter:
    enc = db.get(Encounter, encounter_id)
    if enc is None or enc.org_id != user.org_id:
        raise not_found("Encounter not found")
    return enc


def require_draft(enc: Encounter) -> None:
    if enc.status != "draft":
        raise conflict(f"Encounter is {enc.status}")


def pack_for(enc: Encounter) -> Pack:
    pack = get_pack(enc.pack_id)
    if pack is None:
        raise not_found("Pack not available")
    return pack


def answers_for(db: Session, enc: Encounter) -> dict[str, Any]:
    row = db.get(ExamAnswers, enc.id)
    return dict(row.answers) if row else {}


def latest_ai(db: Session, enc: Encounter) -> AIResult | None:
    return db.scalars(
        select(AIResult).where(AIResult.encounter_id == enc.id).order_by(AIResult.created_at.desc()).limit(1)
    ).first()


def assessments(db: Session, enc: Encounter) -> dict[str, Assessment]:
    rows = db.scalars(select(Assessment).where(Assessment.encounter_id == enc.id)).all()
    return {a.phase: a for a in rows}


def current_assessment(db: Session, enc: Encounter) -> Assessment | None:
    a = assessments(db, enc)
    return a.get("post_reveal") or a.get("pre_reveal")


def active_photos(db: Session, enc: Encounter) -> list[Photo]:
    return list(
        db.scalars(
            select(Photo)
            .where(Photo.encounter_id == enc.id, Photo.deleted_at.is_(None))
            .order_by(Photo.created_at)
        ).all()
    )


def patient_age(patient: Patient) -> int | None:
    return patient.age_on(date.today())


def facts_for(db: Session, enc: Encounter, *, include_model: bool = True) -> dict[str, Any]:
    pack = pack_for(enc)
    patient = db.get(Patient, enc.patient_id)
    assert patient
    ai = latest_ai(db, enc) if include_model else None
    a = current_assessment(db, enc)
    return build_facts(
        pack,
        patient_age=patient_age(patient),
        patient_sex=patient.sex,
        answers=answers_for(db, enc),
        probabilities=ai.probabilities if ai else None,
        suspected=[d["condition_id"] for d in a.diagnoses] if a else [],
    )


# ---------- photos ----------


def add_photo(
    db: Session, storage: Storage, user: User, enc: Encounter, view: str, data: bytes, source: str
) -> Photo:
    require_draft(enc)
    pack = pack_for(enc)
    assert pack.capture_protocol
    if view not in {v.id for v in pack.capture_protocol.views}:
        raise unprocessable(f"Unknown view {view!r}")
    try:
        max_edge = int(pack.capture_protocol.quality.get("max_long_edge", 1600))
        clean, width, height = sanitize_photo(data, max_long_edge=max_edge)
    except Exception:
        raise unprocessable("File is not a readable image") from None
    quality = check_quality(load_rgb(clean), pack.capture_protocol, view)
    photo = Photo(
        org_id=enc.org_id,
        encounter_id=enc.id,
        view=view,
        width=width,
        height=height,
        source=source,
        quality=quality,
        storage_key="",
    )
    db.add(photo)
    db.flush()
    photo.storage_key = photo_key(enc.org_id, enc.id, photo.id)
    storage.put(photo.storage_key, clean, "image/jpeg")
    audit(db, user, "create", "photo", photo.id, {"encounter_id": enc.id, "view": view})
    db.commit()
    return photo


def photo_out(storage: Storage, p: Photo) -> dict:
    deleted = p.deleted_at is not None
    return {
        "id": p.id,
        "view": p.view,
        "width": p.width,
        "height": p.height,
        "source": p.source,
        "quality": p.quality,
        "quality_override_reason": p.quality_override_reason,
        "deleted": deleted,
        "url": None if deleted else storage.signed_url(p.storage_key, get_settings().signed_url_ttl_seconds),
    }


def delete_photo_files(db: Session, storage: Storage, user: User | None, enc: Encounter, reason: str) -> int:
    count = 0
    for p in active_photos(db, enc):
        storage.delete(p.storage_key)
        p.deleted_at = utcnow()
        count += 1
    enc.photos_deleted_at = utcnow()
    audit(db, user, "delete", "photos", enc.id, {"count": count, "reason": reason}, org_id=enc.org_id)
    return count


def required_views(db: Session, enc: Encounter) -> list[str]:
    """Base required views plus conditional ones. Model facts count only for visible conditions,
    so the capture flow never hints at hidden (shadow / reveal_after) output."""
    pack = pack_for(enc)
    assert pack.capture_protocol
    facts = facts_for(db, enc, include_model=False)
    ai = latest_ai(db, enc)
    if ai:
        for cid in visibility.allowed_conditions(ai, visibility.BEFORE_ASSESSMENT):
            facts[f"model.{cid}"] = ai.probabilities.get(cid)
    views = [v.id for v in pack.capture_protocol.views if v.required]
    for cv in pack.capture_protocol.conditional_views:
        if expr.evaluate(cv.when, facts):
            views += [v for v in cv.require if v not in views]
    return views


# ---------- exam ----------


def save_exam(db: Session, user: User, enc: Encounter, answers: dict[str, Any]) -> dict[str, Any]:
    require_draft(enc)
    pack = pack_for(enc)
    errors = validate_answers(pack, answers)
    if errors:
        raise unprocessable(errors)
    row = db.get(ExamAnswers, enc.id)
    if row is None:
        row = ExamAnswers(encounter_id=enc.id, answers={})
        db.add(row)
    row.answers = {k: v for k, v in answers.items() if v is not None}
    db.flush()
    retriage(db, enc)
    audit(db, user, "edit", "exam", enc.id)
    db.commit()
    return row.answers


# ---------- triage, analysis, reveal ----------


def retriage(db: Session, enc: Encounter) -> TriageResult:
    """Re-run rules and sync alerts. Acknowledgements are kept; alerts that no longer apply go inactive."""
    pack = pack_for(enc)
    ai = latest_ai(db, enc)
    facts = facts_for(db, enc)
    result = run_triage(pack, facts, ai.probabilities if ai else None, ai.condition_states if ai else None)

    existing = {
        (a.rule_id, a.subject): a
        for a in db.scalars(select(RedFlagAlert).where(RedFlagAlert.encounter_id == enc.id)).all()
    }
    seen = set()
    for alert in result.alerts:
        key = (alert.rule_id, alert.subject)
        seen.add(key)
        shown = alert.shown
        if ai and ai.revealed_at and ai.condition_states.get(alert.subject) == "reveal_after":
            shown = True  # model alerts for reveal_after conditions show once the AI is revealed
        row = existing.get(key)
        if row is None:
            row = RedFlagAlert(
                org_id=enc.org_id,
                encounter_id=enc.id,
                rule_id=alert.rule_id,
                subject=alert.subject,
                shown=shown,
            )
            db.add(row)
        else:
            row.shown = row.shown or shown  # once shown, an alert stays shown
        row.severity, row.message, row.source = alert.severity, alert.message, alert.source
        row.referral, row.active = alert.referral, True
    for key, row in existing.items():
        if key not in seen:
            row.active = False
    db.flush()
    return result


def alert_out(a: RedFlagAlert) -> dict:
    return {
        "id": a.id,
        "rule_id": a.rule_id,
        "severity": a.severity,
        "message": a.message,
        "referral": a.referral,
        "acknowledged": a.acknowledged_at is not None,
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
    }


def shown_alerts(db: Session, enc: Encounter) -> list[RedFlagAlert]:
    return list(
        db.scalars(
            select(RedFlagAlert).where(
                RedFlagAlert.encounter_id == enc.id,
                RedFlagAlert.shown.is_(True),
                RedFlagAlert.active.is_(True),
            )
        ).all()
    )


def analyze(db: Session, storage: Storage, user: User, enc: Encounter) -> dict:
    require_draft(enc)
    pack = pack_for(enc)
    photos = active_photos(db, enc)
    classifier = get_classifier(pack.id)
    ai: AIResult | None = None

    if classifier and photos:
        images: list[Image.Image] = [load_rgb(storage.get(p.storage_key)) for p in photos]
        probabilities = classifier.predict(images)
        states = resolve_condition_states(db, pack, enc.org_id, classifier.model_version)
        probabilities = {cid: p for cid, p in probabilities.items() if states.get(cid, "off") != "off"}
        ai = AIResult(
            org_id=enc.org_id,
            encounter_id=enc.id,
            model_version=classifier.model_version,
            classifier_kind=classifier.kind,
            probabilities=probabilities,
            condition_states={cid: states[cid] for cid in probabilities},
        )
        if "pre_reveal" in assessments(db, enc):
            ai.revealed_at = utcnow()  # assessment already saved: nothing left to keep independent
        db.add(ai)
        db.flush()
        ai.shown_conditions = [
            s["condition_id"] for s in visibility.suggestions(pack, ai, visibility.BEFORE_ASSESSMENT)
        ]

    triage = retriage(db, enc)
    audit(db, user, "analyze", "encounter", enc.id, {"model_version": ai.model_version if ai else None})
    db.commit()
    return analysis_out(db, enc, pack, ai, triage.suggested_urgency)


def analysis_out(
    db: Session, enc: Encounter, pack: Pack, ai: AIResult | None, suggested_urgency: str
) -> dict:
    suggestions = visibility.suggestions(pack, ai, visibility.BEFORE_ASSESSMENT) if ai else []
    has_hidden = bool(ai and visibility.allowed_conditions(ai, frozenset({"reveal_after"})))
    if suggestions and suggestions[0]["likelihood"] != "low" and suggestions[0]["default_urgency"]:
        suggested_urgency = max_urgency(suggested_urgency, suggestions[0]["default_urgency"])
    return {
        "red_flags": [alert_out(a) for a in shown_alerts(db, enc)],
        "suggested_urgency": suggested_urgency,
        "ai": {
            "available": ai is not None,
            "suggestions": suggestions,
            "compare_after_assessment": has_hidden,
            **(visibility.label(ai) if ai else {}),
        },
        "required_views": required_views(db, enc),
        "missing_fields": missing_required(pack, facts_for(db, enc, include_model=False)),
    }


def ai_compare(db: Session, user: User, enc: Encounter) -> dict:
    """Reveal reveal_after output. 409 until the clinician's own assessment is saved (FR-20a)."""
    if "pre_reveal" not in assessments(db, enc):
        raise conflict("Save your assessment before comparing with AI")
    pack = pack_for(enc)
    ai = latest_ai(db, enc)
    if ai is None:
        return {"available": False, "suggestions": []}
    if ai.revealed_at is None:
        ai.revealed_at = utcnow()
        retriage(db, enc)
    audit(db, user, "reveal", "ai_result", ai.id)
    db.commit()
    return {
        "available": True,
        "suggestions": visibility.suggestions(pack, ai, visibility.AFTER_ASSESSMENT),
        "red_flags": [alert_out(a) for a in shown_alerts(db, enc)],
        **visibility.label(ai),
    }


def acknowledge_alert(db: Session, user: User, enc: Encounter, alert_id: str) -> dict:
    alert = db.get(RedFlagAlert, alert_id)
    if alert is None or alert.encounter_id != enc.id or not alert.shown:
        raise not_found("Alert not found")
    if alert.acknowledged_at is None:
        alert.acknowledged_by = user.id
        alert.acknowledged_at = utcnow()
        audit(db, user, "acknowledge", "red_flag", alert.id, {"rule_id": alert.rule_id})
        db.commit()
    return alert_out(alert)


# ---------- jobs ----------


def run_photo_retention(db: Session, storage: Storage, now: datetime | None = None) -> dict[str, int]:
    """Delete photos of drafts older than PHOTO_DRAFT_TTL_HOURS (FR-8a) and any leftovers of finished encounters."""
    now = now or utcnow()
    cutoff = now - timedelta(hours=get_settings().photo_draft_ttl_hours)
    expired = cleaned = 0
    drafts = db.scalars(select(Encounter).where(Encounter.status == "draft")).all()
    for enc in drafts:
        if as_utc(enc.created_at) > cutoff:  # type: ignore[operator]
            continue
        signed_note = db.scalar(
            select(Report).where(Report.encounter_id == enc.id, Report.status == "signed").limit(1)
        )
        enc.status = "signed" if signed_note else "expired"
        delete_photo_files(db, storage, None, enc, "draft_expired")
        expired += 1
    leftovers = db.scalars(
        select(Encounter).where(Encounter.status != "draft", Encounter.photos_deleted_at.is_(None))
    ).all()
    for enc in leftovers:
        delete_photo_files(db, storage, None, enc, "retention_sweep")
        cleaned += 1
    db.commit()
    return {"expired": expired, "cleaned": cleaned}
