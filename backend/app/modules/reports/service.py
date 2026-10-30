from __future__ import annotations

import base64
from datetime import date
from typing import Any

from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import conflict, not_found, unprocessable
from app.core.storage import Storage
from app.modules.assessment.models import Assessment
from app.modules.audit.service import audit
from app.modules.encounters import service as enc_service
from app.modules.encounters.models import Encounter
from app.modules.llm import client as llm_client
from app.modules.llm.payload import AllowlistedPayload, PayloadCondition, PayloadFinding
from app.modules.orgs.models import Organization, User
from app.modules.packs.loader import Pack, missing_required
from app.modules.patients.models import Patient
from app.modules.referrals.models import Referral
from app.modules.reports.models import Report
from app.modules.reports.pdf import render_pdf
from app.modules.triage.engine import max_urgency

REPORT_TYPES = ("exam_note", "referral_letter", "patient_handout")
_env = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, autoescape=False)

# Generic UI words shared by every pack.
_WORDS = {
    "en": {
        "yes": "Yes",
        "no": "No",
        "right": "right",
        "left": "left",
        "both": "both",
        "referred": "Referred by clinician",
        "notes": "Additional notes",
    },
    "fil": {
        "yes": "Oo",
        "no": "Hindi",
        "right": "kanan",
        "left": "kaliwa",
        "both": "pareho",
        "referred": "Ini-refer ng clinician",
        "notes": "Karagdagang tala",
    },
}


def _w(locale: str, key: str) -> str:
    return _WORDS.get(locale, _WORDS["en"])[key]


def _t(text: dict[str, str] | None, locale: str) -> str:
    if not text:
        return ""
    return text.get(locale) or text.get("en") or next(iter(text.values()), "")


# ---------- context ----------


def _findings(pack: Pack, answers: dict[str, Any], locale: str, include_free_text: bool) -> list[dict]:
    assert pack.exam_form
    out = []
    for f in pack.exam_form.fields:
        value = answers.get(f.id)
        if value in (None, "", []) or (f.free_text and not include_free_text):
            continue
        labels = {o.value: _t(o.label, locale) for o in f.options}
        if f.type == "multi":
            shown = ", ".join(labels.get(v, v) for v in value)
        elif f.type == "single":
            shown = labels.get(value, value)
        elif f.type == "boolean":
            shown = _w(locale, "yes" if value else "no")
        else:
            shown = str(value)
        out.append({"label": _t(f.label, locale), "value": shown, "free_text": f.free_text})
    return out


def referral_reasons(db: Session, enc: Encounter, pack: Pack, a: Assessment, locale: str) -> list[str]:
    reasons: list[str] = []
    dx_ids = [d["condition_id"] for d in a.diagnoses]
    for cid in dx_ids:
        c = pack.condition(cid)
        if c and c.always_refer:
            reasons.append(_t(c.referral_reason, locale))
    for item in a.plan.get("items", []):
        option = pack.management_option(item, dx_ids)
        if option and option.referral:
            reasons.append(_t(option.text, locale))
    for alert in enc_service.shown_alerts(db, enc):
        if alert.referral:
            reasons.append(_t(alert.message, locale))
    if a.plan.get("refer") and not reasons:
        reasons.append(_w(locale, "referred"))
    return list(dict.fromkeys(r for r in reasons if r))


def needs_referral(db: Session, enc: Encounter, pack: Pack, a: Assessment) -> bool:
    return bool(referral_reasons(db, enc, pack, a, "en"))


def build_context(db: Session, enc: Encounter, locale: str, signer: User | None) -> dict[str, Any]:
    pack = enc_service.pack_for(enc)
    a = enc_service.current_assessment(db, enc)
    if a is None:
        raise conflict("Save an assessment before drafting reports")
    patient = db.get(Patient, enc.patient_id)
    org = db.get(Organization, enc.org_id)
    clinician = signer or db.get(User, a.clinician_id)
    assert patient and org and clinician
    answers = enc_service.answers_for(db, enc)
    dx_ids = [d["condition_id"] for d in a.diagnoses]
    plan = [_t(o.text, locale) for i in a.plan.get("items", []) if (o := pack.management_option(i, dx_ids))]
    if a.plan.get("notes"):
        plan.append(a.plan["notes"])
    diagnoses = []
    for d in a.diagnoses:
        c = pack.condition(d["condition_id"])
        diagnoses.append(
            {
                "condition_id": d["condition_id"],
                "name": _t(c.name, locale) if c else d["condition_id"],
                "side": _w(locale, d["side"]) if d.get("side") else None,
                "note": d.get("note"),
                "explainer": pack.content.get(locale, pack.content.get("en", {})).get(d["condition_id"]),
            }
        )
    age = enc_service.patient_age(patient)
    urgency = max_urgency(
        a.urgency,
        *[
            c.pediatric_urgency
            for cid in dx_ids
            if (c := pack.condition(cid)) and age is not None and age < pack.pediatric_age_threshold
        ],
    )
    return {
        "date": date.today().isoformat(),
        "patient": {"name": patient.full_name, "age": age, "sex": patient.sex},
        "clinician": {"name": clinician.full_name, "license_no": clinician.license_no},
        "clinic": {"name": org.name, "address": org.address},
        "findings": _findings(pack, answers, locale, include_free_text=True),
        "diagnoses": diagnoses,
        "urgency": urgency,
        "plan": plan,
        "referral_reasons": referral_reasons(db, enc, pack, a, locale),
        "red_flags": [_t(al.message, locale) for al in enc_service.shown_alerts(db, enc)],
        "_age_band": "unknown"
        if age is None
        else ("child" if age < pack.pediatric_age_threshold else "adult"),
        "_answers": answers,
        "_assessment": a,
    }


def render(pack: Pack, report_type: str, locale: str, ctx: dict[str, Any]) -> str:
    source = pack.templates.get(f"{report_type}.{locale}") or pack.templates.get(f"{report_type}.en")
    if source is None:
        raise unprocessable(f"No template for {report_type}")
    return _env.from_string(source).render(**ctx).strip() + "\n"


# ---------- drafting ----------


def draft_report(db: Session, user: User, enc: Encounter, report_type: str, locale: str) -> Report:
    if report_type not in REPORT_TYPES:
        raise unprocessable(f"Unknown report type {report_type}")
    pack = enc_service.pack_for(enc)
    if f"{report_type}.{locale}" not in pack.templates:
        locale = "en"
    ctx = build_context(db, enc, locale, None)
    report = Report(
        org_id=enc.org_id,
        encounter_id=enc.id,
        type=report_type,
        locale=locale,
        content=render(pack, report_type, locale, ctx),
        created_by=user.id,
    )
    db.add(report)
    db.flush()
    audit(db, user, "create", "report", report.id, {"type": report_type})
    db.commit()
    return report


def build_llm_payload(db: Session, report: Report) -> tuple[AllowlistedPayload, dict[str, Any]]:
    enc = db.get(Encounter, report.encounter_id)
    assert enc
    pack = enc_service.pack_for(enc)
    ctx = build_context(db, enc, report.locale, None)
    a: Assessment = ctx["_assessment"]
    dx_ids = [d["condition_id"] for d in a.diagnoses]
    payload = AllowlistedPayload(
        report_type=report.type,  # type: ignore[arg-type]
        locale=report.locale,  # type: ignore[arg-type]
        age_band=ctx["_age_band"],
        conditions=[
            PayloadCondition(id=d["condition_id"], name=d["name"], side=a.diagnoses[i].get("side"))
            for i, d in enumerate(ctx["diagnoses"])
        ],
        urgency=ctx["urgency"],
        findings=[
            PayloadFinding(label=f["label"], value=f["value"])
            for f in _findings(pack, ctx["_answers"], report.locale, include_free_text=False)
        ],
        # Library text only; the clinician's own free-text notes never leave the server.
        plan=[
            _t(o.text, report.locale)
            for i in a.plan.get("items", [])
            if (o := pack.management_option(i, dx_ids))
        ],
        referral_reasons=ctx["referral_reasons"],
        red_flags=ctx["red_flags"],
    )
    return payload, ctx


def polish_report(db: Session, user: User, report: Report) -> tuple[Report, bool]:
    if report.status != "draft" or report.type not in REPORT_TYPES:
        raise conflict("Only draft reports can be polished")
    org = db.get(Organization, report.org_id)
    if not (org and org.settings.get("llm_polish")):
        return report, False
    payload, ctx = build_llm_payload(db, report)
    text = llm_client.polish(payload)
    if not text:
        return report, False
    text = (
        text.replace("{{PATIENT_NAME}}", ctx["patient"]["name"])
        .replace("{{DATE}}", ctx["date"])
        .replace("{{CLINICIAN_NAME}}", ctx["clinician"]["name"])
        .replace("{{CLINIC_NAME}}", ctx["clinic"]["name"])
    )
    notes = [d["note"] for d in ctx["diagnoses"] if d.get("note")]
    a: Assessment = ctx["_assessment"]
    if a.plan.get("notes"):
        notes.append(a.plan["notes"])
    if notes:
        text += f"\n\n## {_w(report.locale, 'notes')}\n" + "\n".join(f"- {n}" for n in notes)
    report.content = text.strip() + "\n"
    report.source = "llm"
    audit(db, user, "edit", "report", report.id, {"polished": True})
    db.commit()
    return report, True


def edit_report(db: Session, user: User, report: Report, content: str) -> Report:
    if report.status == "signed":
        raise conflict("Signed reports are locked; add an addendum instead")
    report.content = content
    report.source = "edited"
    audit(db, user, "edit", "report", report.id)
    db.commit()
    return report


def add_addendum(db: Session, user: User, parent: Report, content: str) -> Report:
    if parent.status != "signed":
        raise conflict("Addenda are only for signed reports; edit the draft instead")
    add = Report(
        org_id=parent.org_id,
        encounter_id=parent.encounter_id,
        type="addendum",
        locale=parent.locale,
        content=content,
        source="edited",
        parent_report_id=parent.id,
        created_by=user.id,
    )
    db.add(add)
    db.flush()
    audit(db, user, "create", "report", add.id, {"type": "addendum", "parent": parent.id})
    db.commit()
    return add


# ---------- sign-off ----------


def sign_off_problems(db: Session, enc: Encounter, pack: Pack) -> list[str]:
    problems = []
    a = enc_service.current_assessment(db, enc)
    if a is None:
        return ["No assessment saved"]
    for alert in enc_service.shown_alerts(db, enc):
        if alert.acknowledged_at is None:
            problems.append(f"Red-flag alert not acknowledged: {_t(alert.message, 'en')}")
    facts = enc_service.facts_for(db, enc, include_model=False)
    problems += [f"Required exam field missing: {f}" for f in missing_required(pack, facts)]
    answers = enc_service.answers_for(db, enc)
    for d in a.diagnoses:
        c = pack.condition(d["condition_id"])
        if not c or not c.required_exam_fields_by_side:
            continue
        side = d.get("side")
        if side is None:
            problems.append(f"Specify the side for {c.name.get('en', c.id)}")
            continue
        by_side: dict[str, list[str]] = {str(k): v for k, v in c.required_exam_fields_by_side.items()}
        for s in ["right", "left"] if side == "both" else [side]:
            for field in by_side.get(s, []):
                if not answers.get(field):
                    problems.append(f"{c.name.get('en', c.id)} requires exam field {field}")
    return problems


def _create_referral(db: Session, enc: Encounter, pack: Pack, a: Assessment) -> Referral | None:
    reasons = referral_reasons(db, enc, pack, a, "en")
    if not reasons:
        return None
    ctx_urgency = build_context(db, enc, "en", None)["urgency"]
    alerts = [al.severity for al in enc_service.shown_alerts(db, enc) if al.referral]
    ref = Referral(
        org_id=enc.org_id,
        encounter_id=enc.id,
        patient_id=enc.patient_id,
        urgency=max_urgency(ctx_urgency, *alerts),
        reasons=reasons,
    )
    db.add(ref)
    return ref


def _pdf(db: Session, storage: Storage, report: Report, enc: Encounter, with_photos: bool) -> bytes:
    org = db.get(Organization, enc.org_id)
    signer = db.get(User, report.signed_by) if report.signed_by else None
    assert org
    if report.status == "signed" and signer:
        lic = f", Lic. {signer.license_no}" if signer.license_no else ""
        footer = f"Signed by {signer.full_name}{lic} on {report.signed_at:%Y-%m-%d %H:%M} UTC"
    else:
        footer = "DRAFT - not signed"
    photos = []
    if with_photos:
        pack = enc_service.pack_for(enc)
        assert pack.capture_protocol
        labels = {v.id: _t(v.label, report.locale) for v in pack.capture_protocol.views}
        photos = [
            (labels.get(p.view, p.view), storage.get(p.storage_key))
            for p in enc_service.active_photos(db, enc)
        ]
    return render_pdf(
        report.content, clinic_name=org.name, clinic_address=org.address, footer_text=footer, photos=photos
    )


def report_pdf(db: Session, storage: Storage, user: User, report: Report) -> bytes:
    enc = db.get(Encounter, report.encounter_id)
    assert enc
    data = _pdf(db, storage, report, enc, with_photos=enc.photos_deleted_at is None)
    audit(db, user, "export", "report", report.id, {"photos": enc.photos_deleted_at is None})
    db.commit()
    return data


def sign_off(db: Session, storage: Storage, user: User, enc: Encounter, report_ids: list[str]) -> dict:
    """Sign reports. On a draft encounter this finalizes it: referral, PDFs with photos, photo deletion (11.1)."""
    pack = enc_service.pack_for(enc)
    found = [db.get(Report, rid) for rid in report_ids]
    reports = [r for r in found if r is not None and r.encounter_id == enc.id]
    if not reports or len(reports) != len(found):
        raise not_found("Report not found")
    if any(r.status == "signed" for r in reports):
        raise conflict("Report already signed")

    finalizing = enc.status == "draft"
    if enc.status == "expired":
        raise conflict("Encounter expired")
    problems = sign_off_problems(db, enc, pack)
    if finalizing:
        signed_note = db.scalar(
            select(Report).where(
                Report.encounter_id == enc.id, Report.type == "exam_note", Report.status == "signed"
            )
        )
        if not signed_note and not any(r.type == "exam_note" for r in reports):
            problems.append("The exam note must be signed to finish the encounter")
    if problems:
        raise unprocessable(problems)

    now = utcnow()
    for r in reports:
        r.status, r.signed_by, r.signed_at = "signed", user.id, now
        audit(db, user, "sign", "report", r.id)
    db.flush()

    referral = None
    pdfs = {r.id: _pdf(db, storage, r, enc, with_photos=finalizing) for r in reports}
    if finalizing:
        a = enc_service.current_assessment(db, enc)
        assert a
        referral = _create_referral(db, enc, pack, a)
        enc.status, enc.signed_by, enc.signed_at = "signed", user.id, now
        enc_service.delete_photo_files(db, storage, user, enc, "signed")
    db.commit()
    return {
        "encounter_status": enc.status,
        "photos_deleted": enc.photos_deleted_at is not None,
        "referral_id": referral.id if referral else None,
        "reports": [{**report_out(r), "pdf_base64": base64.b64encode(pdfs[r.id]).decode()} for r in reports],
    }


def report_out(r: Report) -> dict:
    return {
        "id": r.id,
        "encounter_id": r.encounter_id,
        "type": r.type,
        "locale": r.locale,
        "status": r.status,
        "content": r.content,
        "source": r.source,
        "parent_report_id": r.parent_report_id,
        "signed_at": r.signed_at.isoformat() if r.signed_at else None,
        "created_at": r.created_at.isoformat(),
    }
