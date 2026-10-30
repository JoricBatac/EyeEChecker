"""Stateless diagnosis assist (mobile-only mode).

Flow: analyze (photos + exam) -> clinician's own pick -> reveal AI ranking -> report text.
Photos are processed in memory and never written anywhere. The model output travels back to the phone
inside an encrypted, expiring token, so the server keeps no case state and the phone cannot read the AI
ranking before the clinician has committed to an impression.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import date
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image
from pydantic import BaseModel, Field
from scanassist_core.preprocess import load_rgb, sanitize_photo
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import expr
from app.core.config import get_settings
from app.core.db import new_id
from app.core.errors import conflict, unprocessable
from app.modules.assist.models import AccessCode, AssistScore
from app.modules.inference.classifiers import get_classifier
from app.modules.packs.loader import Pack, missing_required, validate_answers
from app.modules.packs.states import resolve_condition_states
from app.modules.quality.checks import check_quality
from app.modules.reports.service import REPORT_TYPES, _findings, _t, _w, render
from app.modules.triage.engine import Alert, build_facts, max_urgency, run_triage

TOKEN_TTL_SECONDS = 2 * 60 * 60
REVEALABLE = frozenset({"reveal_after", "visible"})
PATIENT_NAME = "{{PATIENT_NAME}}"  # filled in on the phone; the server never sees the name


# ---------- access codes ----------


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def check_code(db: Session, code: str | None) -> AccessCode | None:
    if not code:
        return None
    row = db.scalar(
        select(AccessCode).where(AccessCode.code_hash == hash_code(code), AccessCode.active.is_(True))
    )
    if row and row.last_used_on != date.today():
        row.last_used_on = date.today()
        db.commit()
    return row


# ---------- sealed analysis token ----------


def _fernet() -> Fernet:
    key = hashlib.sha256(("assist-token:" + get_settings().jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def unseal(token: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode(), ttl=TOKEN_TTL_SECONDS))
    except (InvalidToken, ValueError):
        raise conflict("Analysis expired or invalid; analyze the photos again") from None


# ---------- helpers ----------


def clean_answers(pack: Pack, answers: dict[str, Any]) -> dict[str, Any]:
    """Drop free-text fields (they stay on the phone) and validate the rest."""
    free = {f.id for f in (pack.exam_form.fields if pack.exam_form else []) if f.free_text}
    kept = {k: v for k, v in answers.items() if k not in free and v is not None}
    errors = validate_answers(pack, kept)
    if errors:
        raise unprocessable(errors)
    return kept


def age_band(pack: Pack, age: int | None) -> str:
    if age is None:
        return "unknown"
    return "child" if age < pack.pediatric_age_threshold else "adult"


def _alert_out(a: Alert) -> dict:
    return {
        "rule_id": a.rule_id,
        "subject": a.subject,
        "key": f"{a.rule_id}:{a.subject}",
        "severity": a.severity,
        "message": a.message,
        "referral": a.referral,
    }


def _assist_states(db: Session, pack: Pack, model_version: str) -> dict[str, str]:
    # In assist mode the AI is never shown before the clinician's pick, so "visible" behaves as reveal_after.
    states = resolve_condition_states(db, pack, "", model_version)
    return {cid: ("reveal_after" if s == "visible" else s) for cid, s in states.items()}


def _triage(pack: Pack, sealed: dict[str, Any], suspected: list[str], revealed: bool):
    probs = sealed.get("probabilities") or None
    states = dict(sealed.get("states") or {})
    if revealed:
        states = {cid: ("visible" if s in REVEALABLE else s) for cid, s in states.items()}
    facts = build_facts(
        pack,
        patient_age=sealed.get("age"),
        patient_sex=sealed.get("sex"),
        answers=sealed["answers"],
        probabilities=probs,
        suspected=suspected,
    )
    return run_triage(pack, facts, probs, states), facts


def _required_views(pack: Pack, facts: dict[str, Any], sealed: dict[str, Any], revealed: bool) -> list[str]:
    assert pack.capture_protocol
    view_facts = {k: v for k, v in facts.items() if not k.startswith("model.")}
    if revealed:  # model facts may drive extra views only once the AI is visible
        view_facts.update({k: v for k, v in facts.items() if k.startswith("model.")})
    views = [v.id for v in pack.capture_protocol.views if v.required]
    for cv in pack.capture_protocol.conditional_views:
        if expr.evaluate(cv.when, view_facts):
            views += [v for v in cv.require if v not in views]
    return views


def _band(pack: Pack, p: float) -> str:
    if p >= pack.likelihood_bands.get("high", 0.6):
        return "high"
    return "moderate" if p >= pack.likelihood_bands.get("moderate", 0.3) else "low"


# ---------- endpoints ----------


def quality(pack: Pack, view: str, data: bytes) -> dict:
    assert pack.capture_protocol
    if view not in {v.id for v in pack.capture_protocol.views}:
        raise unprocessable(f"Unknown view {view!r}")
    try:
        clean, _, _ = sanitize_photo(data, int(pack.capture_protocol.quality.get("max_long_edge", 1600)))
    except Exception:
        raise unprocessable("File is not a readable image") from None
    return check_quality(load_rgb(clean), pack.capture_protocol, view)


def _seal_analysis(
    db: Session,
    pack: Pack,
    photos: list[tuple[str, bytes]],
    answers: dict[str, Any],
    age: int | None,
    sex: str | None,
) -> tuple[dict[str, Any], list[dict]]:
    """Run quality checks and the model on in-memory photos. Returns the sealed payload and photo quality."""
    assert pack.capture_protocol
    answers = clean_answers(pack, answers)
    view_ids = {v.id for v in pack.capture_protocol.views}
    images: list[Image.Image] = []
    photo_quality = []
    for view, data in photos:
        if view not in view_ids:
            raise unprocessable(f"Unknown view {view!r}")
        try:
            clean, _, _ = sanitize_photo(data, int(pack.capture_protocol.quality.get("max_long_edge", 1600)))
        except Exception:
            raise unprocessable(f"Photo for {view} is not a readable image") from None
        img = load_rgb(clean)
        images.append(img)
        photo_quality.append({"view": view, **check_quality(img, pack.capture_protocol, view)})

    classifier = get_classifier(pack.id)
    probs: dict[str, float] = {}
    states: dict[str, str] = {}
    model_version = kind = None
    if classifier and images:
        states = _assist_states(db, pack, classifier.model_version)
        probs = {c: p for c, p in classifier.predict(images).items() if states.get(c, "off") != "off"}
        states = {c: states[c] for c in probs}
        model_version, kind = classifier.model_version, classifier.kind

    sealed = {
        "aid": new_id(),
        "pack_id": pack.id,
        "model_version": model_version,
        "classifier_kind": kind,
        "probabilities": probs,
        "states": states,
        "answers": answers,
        "age": age,
        "sex": sex,
    }
    return sealed, photo_quality


def analyze(
    db: Session,
    pack: Pack,
    photos: list[tuple[str, bytes]],
    answers: dict[str, Any],
    age: int | None,
    sex: str | None,
) -> dict:
    """Reveal-after-pick flow: red flags now, AI ranking only after the clinician's impression."""
    sealed, photo_quality = _seal_analysis(db, pack, photos, answers, age, sex)
    probs, states = sealed["probabilities"], sealed["states"]
    triage, facts = _triage(pack, sealed, [], revealed=False)
    return {
        "analysis_token": seal(sealed),
        "photos": photo_quality,
        "red_flags": [_alert_out(a) for a in triage.shown_alerts],
        "suggested_urgency": triage.suggested_urgency,
        "required_views": _required_views(pack, facts, sealed, revealed=False),
        "missing_fields": missing_required(
            pack, {k: v for k, v in facts.items() if not k.startswith("model.")}
        ),
        "ai_available": bool(probs and any(s in REVEALABLE for s in states.values())),
    }


class PickIn(BaseModel):
    condition_id: str
    side: Literal["right", "left", "both"] | None = None


class RevealIn(BaseModel):
    analysis_token: str
    diagnoses: list[PickIn] = Field(min_length=1)
    urgency: Literal["routine", "soon", "urgent"]


def _check_picks(pack: Pack, picks: list[PickIn]) -> list[str]:
    ids = [p.condition_id for p in picks]
    unknown = [c for c in ids if pack.condition(c) is None]
    if unknown:
        raise unprocessable([f"unknown condition {c}" for c in unknown])
    return ids


def reveal(db: Session, pack: Pack, code: AccessCode, body: RevealIn) -> dict:
    """The clinician has committed to an impression: log it, then show the AI ranking."""
    sealed = unseal(body.analysis_token)
    if sealed["pack_id"] != pack.id:
        raise conflict("Analysis belongs to another pack")
    picks = _check_picks(pack, body.diagnoses)
    probs: dict[str, float] = sealed["probabilities"]
    states: dict[str, str] = sealed["states"]
    triage, facts = _triage(pack, sealed, picks, revealed=True)

    score = db.scalar(select(AssistScore).where(AssistScore.analysis_id == sealed["aid"]))
    if score is None and probs:
        # First reveal only: the pre-AI impression is never overwritten.
        db.add(
            AssistScore(
                analysis_id=sealed["aid"],
                access_code_id=code.id,
                pack_id=pack.id,
                model_version=sealed["model_version"],
                probabilities=probs,
                condition_states=states,
                age_band=age_band(pack, sealed.get("age")),
                red_flags=sorted({a.rule_id for a in triage.shown_alerts}),
                clinician_dx=picks,
                clinician_urgency=body.urgency,
            )
        )
        db.commit()

    ranked = sorted(
        ((c, p) for c, p in probs.items() if states.get(c) in REVEALABLE), key=lambda x: x[1], reverse=True
    )
    top = [
        {
            "condition_id": c,
            "name": pack.condition(c).name if pack.condition(c) else {"en": c},  # type: ignore[union-attr]
            "likelihood": _band(pack, p),
            "probability": p,
        }
        for c, p in ranked[:3]
    ]
    top_ids = [t["condition_id"] for t in top]
    agreement = (
        "not_shown"
        if not top
        else "agreed"
        if picks[0] == top_ids[0]
        else "partial"
        if set(picks) & set(top_ids)
        else "differs"
    )
    return {
        "label": "AI suggestion, for clinician review",
        "model_version": sealed["model_version"],
        "suggestions": top,
        "agreement": agreement,
        "red_flags": [_alert_out(a) for a in triage.shown_alerts],
        "required_views": _required_views(pack, facts, sealed, revealed=True),
    }


def _explain(pack: Pack, cid: str, p: float, facts: dict[str, Any]) -> dict:
    """Why a condition is suggested: what it looks like, and which exam answers fit or don't.

    The ranking itself comes only from the image model; evidence is explanatory and never changes scores.
    """
    c = pack.condition(cid)
    supports: list[dict[str, str]] = []
    against: list[dict[str, str]] = []
    for ev in c.evidence if c else []:
        if expr.evaluate(ev.when, facts):
            (supports if ev.direction == "supports" else against).append(ev.text)
    return {
        "condition_id": cid,
        "name": c.name if c else {"en": cid},
        "probability": p,
        "likelihood": _band(pack, p),
        "default_urgency": c.default_urgency if c else None,
        "emergency": bool(c and c.emergency),
        "visual_features": c.visual_features if c else None,
        "supports": supports,
        "against": against,
    }


def quick(
    db: Session,
    pack: Pack,
    photos: list[tuple[str, bytes]],
    lighting: list[str],
    answers: dict[str, Any],
    age: int | None,
    sex: str | None,
) -> dict:
    """Simple flow: photo(s) in, AI ranking with explanations out, immediately. Nothing is stored."""
    assert pack.capture_protocol
    lv = pack.capture_protocol.lighting_views
    default_view = lv.get("normal") or pack.capture_protocol.views[0].id
    views = [lv.get(tag or "normal", default_view) for tag in lighting]
    sealed, photo_quality = _seal_analysis(
        db, pack, list(zip(views, [d for _, d in photos], strict=True)), answers, age, sex
    )
    sealed["mode"] = "quick"
    for q, tag in zip(photo_quality, lighting, strict=True):
        q["lighting"] = tag or "normal"
    response, facts = _quick_response(pack, sealed)
    return {
        **response,
        "photos": photo_quality,
        "recommended_views": [
            v for v in _required_views(pack, facts, sealed, revealed=True) if v not in views
        ],
    }


AGE_QUESTION = "age"  # pseudo field: age is asked like an exam question in the follow-up


def _fields_in(e: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("all", "any"):
        for sub in e.get(key, []):
            out |= _fields_in(sub)
    if "not" in e:
        out |= _fields_in(e["not"])
    fact = e.get("fact", "")
    if isinstance(fact, str) and fact.startswith("exam."):
        out.add(fact.removeprefix("exam."))
    elif fact in ("patient.age", "patient.is_pediatric"):
        out.add(AGE_QUESTION)
    return out


def follow_up_questions(
    pack: Pack, results: list[dict], answers: dict[str, Any], age: int | None, limit: int = 4
) -> list[str]:
    """Pick the few questions worth asking for this photo.

    A question scores for each top suggestion whose explanation depends on it (weighted by that suggestion's
    probability) and for each red-flag rule that uses it. Questions already answered are skipped.
    Nothing here changes the AI ranking; answers only refine the explanation and the safety checks.
    """
    assert pack.ruleset and pack.exam_form
    scores: dict[str, float] = {}
    for r in results:
        c = pack.condition(r["condition_id"])
        for ev in c.evidence if c else []:
            for f in _fields_in(ev.when):
                scores[f] = scores.get(f, 0.0) + 0.5 + r["probability"]
    for rule in pack.ruleset.red_flags:
        for f in _fields_in(rule.when):
            scores[f] = scores.get(f, 0.0) + 0.3
    askable = {f.id for f in pack.exam_form.fields if not f.free_text} | {AGE_QUESTION}
    answered = {k for k, v in answers.items() if v not in (None, "", [])}
    if age is not None:
        answered.add(AGE_QUESTION)
    ranked = sorted((f for f in scores if f in askable and f not in answered), key=lambda f: (-scores[f], f))
    return ranked[:limit]


def _quick_response(pack: Pack, sealed: dict[str, Any]) -> tuple[dict, dict[str, Any]]:
    triage, facts = _triage(pack, sealed, [], revealed=True)
    probs, states = sealed["probabilities"], sealed["states"]
    ranked = sorted(
        ((c, p) for c, p in probs.items() if states.get(c) in REVEALABLE), key=lambda x: x[1], reverse=True
    )
    explained = [_explain(pack, c, p, facts) for c, p in ranked]
    results, others = explained[:3], explained[3:]
    moderate = pack.likelihood_bands.get("moderate", 0.3)
    if not results:
        confidence = "unavailable"
    elif results[0]["probability"] < moderate:
        confidence = "low"  # the photo doesn't clearly match any condition
    elif len(results) > 1 and results[0]["probability"] - results[1]["probability"] < 0.1:
        confidence = "split"  # two causes are close
    else:
        confidence = "clear"
    urgency = triage.suggested_urgency
    if results and confidence == "clear" and results[0]["default_urgency"]:
        urgency = max_urgency(urgency, results[0]["default_urgency"])
    return {
        "analysis_token": seal(sealed),
        "label": "AI suggestion, for clinician review",
        "model_version": sealed["model_version"],
        "results": results,
        "others": others,  # the remaining conditions, lower ranked; shown folded in the app
        "confidence": confidence,
        "red_flags": [_alert_out(a) for a in triage.shown_alerts],
        "suggested_urgency": urgency,
        "answered_questions": len(sealed["answers"]) + (sealed.get("age") is not None),
        "follow_up": follow_up_questions(pack, results, sealed["answers"], sealed.get("age")),
    }, facts


class ExplainIn(BaseModel):
    analysis_token: str
    answers: dict[str, Any] = Field(default_factory=dict)
    age: int | None = Field(default=None, ge=0, le=130)


def explain(pack: Pack, body: ExplainIn) -> dict:
    """Refresh the explanation and red flags with new answers. Reuses the sealed model output: no re-upload."""
    sealed = unseal(body.analysis_token)
    if sealed["pack_id"] != pack.id:
        raise conflict("Analysis belongs to another pack")
    sealed["answers"] = clean_answers(pack, {**sealed["answers"], **body.answers})
    if body.age is not None:
        sealed["age"] = body.age
    response, _ = _quick_response(pack, sealed)
    return response


class ConfirmIn(BaseModel):
    analysis_token: str
    diagnoses: list[PickIn] = Field(min_length=1)
    urgency: Literal["routine", "soon", "urgent"]
    rating: Literal["correct", "wrong_cause", "wrong_urgency", "not_useful"] | None = None


def confirm(db: Session, pack: Pack, code: AccessCode, body: ConfirmIn) -> dict:
    """Clinician confirms a diagnosis after seeing the AI. Logged anonymously, marked as AI-first."""
    sealed = unseal(body.analysis_token)
    picks = _check_picks(pack, body.diagnoses)
    triage, facts = _triage(pack, sealed, picks, revealed=True)
    score = db.scalar(select(AssistScore).where(AssistScore.analysis_id == sealed["aid"]))
    if score is None and sealed["probabilities"]:
        score = AssistScore(
            analysis_id=sealed["aid"],
            access_code_id=code.id,
            pack_id=pack.id,
            model_version=sealed["model_version"],
            probabilities=sealed["probabilities"],
            condition_states=sealed["states"],
            age_band=age_band(pack, sealed.get("age")),
            red_flags=sorted({a.rule_id for a in triage.shown_alerts}),
            clinician_dx=picks,
            clinician_urgency=body.urgency,
            mode=sealed.get("mode", "quick"),
        )
        db.add(score)
    if score is not None:
        score.final_dx = picks
        score.rating = body.rating or score.rating
        db.commit()
    return {
        "red_flags": [_alert_out(a) for a in triage.shown_alerts],
        "recommended_views": _required_views(pack, facts, sealed, revealed=True),
    }


class OutcomeIn(BaseModel):
    analysis_token: str
    final_diagnoses: list[str] = Field(min_length=1)
    rating: Literal["correct", "wrong_cause", "wrong_urgency", "not_useful"] | None = None


def outcome(db: Session, code: AccessCode, body: OutcomeIn) -> dict:
    sealed = unseal(body.analysis_token)
    score = db.scalar(select(AssistScore).where(AssistScore.analysis_id == sealed["aid"]))
    if score is None or score.access_code_id != code.id:
        raise conflict("Reveal the AI ranking before recording the outcome")
    score.final_dx = body.final_diagnoses
    score.changed_after_reveal = body.final_diagnoses != score.clinician_dx
    if body.rating:
        score.rating = body.rating
    db.commit()
    return {"ok": True}


class ReportIn(BaseModel):
    analysis_token: str
    report_type: Literal["exam_note", "referral_letter", "patient_handout"]
    locale: Literal["en", "fil"] = "en"
    diagnoses: list[PickIn] = Field(min_length=1)
    urgency: Literal["routine", "soon", "urgent"]
    plan_items: list[str] = Field(default_factory=list)
    refer: bool = False
    acknowledged: list[str] = Field(default_factory=list)  # red flag keys the clinician acknowledged
    profession: str | None = None
    clinician_name: str = Field(default="", max_length=200)
    clinician_license: str | None = Field(default=None, max_length=50)
    clinic_name: str = Field(default="", max_length=200)
    clinic_address: str | None = Field(default=None, max_length=300)


def report(pack: Pack, body: ReportIn) -> dict:
    """Report text with {{PATIENT_NAME}} left for the phone to fill in."""
    assert body.report_type in REPORT_TYPES
    sealed = unseal(body.analysis_token)
    picks = _check_picks(pack, body.diagnoses)
    triage, _ = _triage(pack, sealed, picks, revealed=True)
    alerts = triage.shown_alerts
    pending = [a for a in alerts if f"{a.rule_id}:{a.subject}" not in body.acknowledged]
    if pending:
        raise unprocessable([f"Red-flag alert not acknowledged: {_t(a.message, 'en')}" for a in pending])

    problems = []
    answers = sealed["answers"]
    for p in body.diagnoses:
        c = pack.condition(p.condition_id)
        if not c or not c.required_exam_fields_by_side:
            continue
        if p.side is None:
            problems.append(f"Specify the side for {c.name.get('en', c.id)}")
            continue
        by_side: dict[str, list[str]] = {str(k): v for k, v in c.required_exam_fields_by_side.items()}
        for s in ["right", "left"] if p.side == "both" else [p.side]:
            problems += [
                f"{c.name.get('en', c.id)} requires exam field {f}"
                for f in by_side.get(s, [])
                if not answers.get(f)
            ]
    for item in body.plan_items:
        option = pack.management_option(item, picks)
        if option is None:
            problems.append(f"unknown management option {item}")
        elif body.profession and body.profession not in option.professions:
            problems.append(f"management option {item} is outside your scope of practice")
    if problems:
        raise unprocessable(problems)

    locale = body.locale if f"{body.report_type}.{body.locale}" in pack.templates else "en"
    reasons: list[str] = []
    for cid in picks:
        c = pack.condition(cid)
        if c and c.always_refer:
            reasons.append(_t(c.referral_reason, locale))
    for item in body.plan_items:
        o = pack.management_option(item, picks)
        if o and o.referral:
            reasons.append(_t(o.text, locale))
    reasons += [_t(a.message, locale) for a in alerts if a.referral]
    if body.refer and not reasons:
        reasons.append(_w(locale, "referred"))
    reasons = list(dict.fromkeys(r for r in reasons if r))

    age = sealed.get("age")
    pediatric = age is not None and age < pack.pediatric_age_threshold
    urgency = max_urgency(
        body.urgency,
        *[c.pediatric_urgency for cid in picks if pediatric and (c := pack.condition(cid))],
        *[a.severity for a in alerts if a.referral],
    )
    ctx = {
        "date": date.today().isoformat(),
        "patient": {"name": PATIENT_NAME, "age": age, "sex": sealed.get("sex")},
        "clinician": {"name": body.clinician_name, "license_no": body.clinician_license},
        "clinic": {"name": body.clinic_name, "address": body.clinic_address},
        "findings": _findings(pack, answers, locale, include_free_text=False),
        "diagnoses": [
            {
                "condition_id": p.condition_id,
                "name": _t(pack.condition(p.condition_id).name, locale),  # type: ignore[union-attr]
                "side": _w(locale, p.side) if p.side else None,
                "note": None,
                "explainer": pack.content.get(locale, pack.content.get("en", {})).get(p.condition_id),
            }
            for p in body.diagnoses
        ],
        "urgency": urgency,
        "plan": [_t(o.text, locale) for i in body.plan_items if (o := pack.management_option(i, picks))],
        "referral_reasons": reasons,
        "red_flags": [_t(a.message, locale) for a in alerts],
    }
    return {
        "content": render(pack, body.report_type, locale, ctx),
        "locale": locale,
        "urgency": urgency,
        "referral_reasons": reasons,
        "placeholders": [PATIENT_NAME],
    }
