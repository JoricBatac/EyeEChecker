"""A.2 / A.3: region guard, LLM allowlist and fallback, audit log, pack rules, scope of practice, ml isolation."""

import json
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings
from app.modules.audit.models import AuditLog
from app.modules.llm import client as llm_client
from app.modules.llm.payload import AllowlistedPayload
from app.modules.orgs.models import Organization
from app.modules.packs.loader import get_pack
from app.modules.reports.models import Report
from app.modules.reports.service import build_llm_payload
from tests.conftest import ack_all, assess, auth, draft, full_encounter

PROD = dict(
    app_env="production",
    storage_backend="s3",
    jwt_secret="x" * 40,
    patient_hash_salt="real-salt",
    database_url="postgresql+psycopg://u:p@db/scanassist",
)


# ---------- region ----------


def test_production_refuses_non_singapore_storage():
    with pytest.raises(RuntimeError, match="asia-southeast1"):
        Settings(**PROD, storage_region="us-central1").validate_for_runtime()
    Settings(**PROD, storage_region="asia-southeast1").validate_for_runtime()


def test_production_refuses_dev_secrets():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(**{**PROD, "jwt_secret": "change-me"}).validate_for_runtime()


# ---------- LLM ----------


def test_llm_payload_rejects_extra_fields():
    base = dict(
        report_type="exam_note",
        locale="en",
        age_band="adult",
        conditions=[],
        urgency="routine",
        findings=[],
        plan=[],
        referral_reasons=[],
        red_flags=[],
    )
    AllowlistedPayload(**base)
    for forbidden in ("patient_name", "photo", "image_url", "patient_id", "notes", "clinic_name"):
        with pytest.raises(ValidationError):
            AllowlistedPayload(**base, **{forbidden: "x"})
    with pytest.raises(ValidationError):
        AllowlistedPayload(**{**base, "conditions": [{"id": "x", "name": "y", "patient": "Juan"}]})


def test_llm_payload_has_no_identifiers_or_free_text(client, db, org_a):
    exam = {
        "affected_side": "right",
        "symptoms": ["redness"],
        "duration": "1_3d",
        "pain_severity": "none",
        "vision_change": "none",
        "contact_lens": False,
        "prior_eye_surgery": ["none"],
        "trauma_or_chemical": "none",
        "notes": "Lives at 12 Mabini St, phone 0917",
    }
    enc = full_encounter(client, org_a.clinician, exam)
    assess(
        client,
        org_a.clinician,
        enc["id"],
        "conj_viral",
        plan={"items": ["hygiene"], "notes": "Call daughter Maria"},
    )
    rpt = draft(client, org_a.clinician, enc["id"])
    payload, _ = build_llm_payload(db, db.get(Report, rpt["id"]))
    dumped = payload.model_dump_json()
    for secret in (
        "Juan",
        "Dela Cruz",
        "Mabini",
        "0917",
        "Maria",
        org_a.org.name,
        org_a.clinician.full_name,
        "http",
    ):
        assert secret not in dumped, secret
    assert set(json.loads(dumped)) == set(AllowlistedPayload.model_fields)


def test_llm_unreachable_falls_back_to_template(client, db, org_a, monkeypatch):
    org = db.get(Organization, org_a.org.id)
    org.settings = {"llm_polish": True}
    db.commit()
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: Settings(
            llm_provider="medgemma_selfhosted", llm_base_url="http://127.0.0.1:9", llm_timeout_ms=300
        ),
    )
    enc = full_encounter(client, org_a.clinician)
    ack_all(client, org_a.clinician, enc["id"])
    assess(client, org_a.clinician, enc["id"])
    rpt = draft(client, org_a.clinician, enc["id"])
    r = client.post(f"/v1/reports/{rpt['id']}/polish", headers=auth(org_a.clinician))
    assert r.status_code == 200
    assert r.json()["polished"] is False
    assert r.json()["content"] == rpt["content"]
    signed = client.post(
        f"/v1/encounters/{enc['id']}/sign-off",
        json={"report_ids": [rpt["id"]]},
        headers=auth(org_a.clinician),
    )
    assert signed.status_code == 200


def test_llm_polish_substitutes_placeholders(client, db, org_a, monkeypatch):
    org = db.get(Organization, org_a.org.id)
    org.settings = {"llm_polish": True}
    db.commit()
    captured = {}

    def fake_post(url, json, timeout):
        captured["body"] = json
        text = "# Note\nPatient {{PATIENT_NAME}} seen on {{DATE}} by {{CLINICIAN_NAME}}."
        return httpx.Response(
            200, json={"choices": [{"message": {"content": text}}]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: Settings(llm_provider="medgemma_selfhosted", llm_base_url="http://llm"),
    )
    enc = full_encounter(client, org_a.clinician)
    assess(client, org_a.clinician, enc["id"])
    rpt = draft(client, org_a.clinician, enc["id"])
    r = client.post(f"/v1/reports/{rpt['id']}/polish", headers=auth(org_a.clinician)).json()
    assert r["polished"] is True
    assert "Juan Dela Cruz" in r["content"]
    assert "Juan" not in json.dumps(captured["body"])


# ---------- audit ----------


def test_views_exports_and_edits_are_audited(client, db, org_a):
    enc = full_encounter(client, org_a.clinician)
    h = auth(org_a.clinician)
    assess(client, org_a.clinician, enc["id"])
    rpt = draft(client, org_a.clinician, enc["id"])
    client.get(f"/v1/patients/{enc['patient']['id']}", headers=h)
    client.get(f"/v1/encounters/{enc['id']}", headers=h)
    client.get(f"/v1/reports/{rpt['id']}/pdf", headers=h)
    client.patch(f"/v1/reports/{rpt['id']}", json={"content": "# Edited"}, headers=h)
    actions = {(a.action, a.entity_type) for a in db.query(AuditLog).filter_by(user_id=org_a.clinician.id)}
    for expected in [
        ("view", "patient"),
        ("view", "encounter"),
        ("export", "report"),
        ("edit", "report"),
        ("edit", "exam"),
        ("edit", "assessment"),
        ("create", "photo"),
    ]:
        assert expected in actions, expected


# ---------- packs ----------


def test_skin_placeholder_cannot_be_enabled(client, org_a, internal):
    r = client.put(
        f"/v1/internal/orgs/{org_a.org.id}/packs/skin",
        json={"enabled": True},
        headers=auth(internal["admin"]),
    )
    assert r.status_code == 409


def test_packs_endpoint_hides_placeholder_and_ruleset(client, org_a):
    packs = client.get("/v1/packs", headers=auth(org_a.clinician)).json()
    assert [p["id"] for p in packs] == ["eye"]
    assert "ruleset" not in packs[0] and "model" not in packs[0]


def test_management_filtered_by_profession(client, org_a):
    def option_ids(user):
        mgmt = client.get("/v1/packs", headers=auth(user)).json()[0]["management"]
        return {o["id"] for o in mgmt["conj_bacterial"]}

    assert "topical_antibiotic" in option_ids(org_a.clinician)
    assert "topical_antibiotic" not in option_ids(org_a.optometrist)

    enc = full_encounter(client, org_a.optometrist)
    r = assess(client, org_a.optometrist, enc["id"], "conj_bacterial", plan={"items": ["topical_antibiotic"]})
    assert r.status_code == 422
    assert "scope of practice" in json.dumps(r.json())


def test_core_has_no_specialty_specific_strings():
    """A.3: no eye-specific logic or strings outside packs/eye."""
    eye = get_pack("eye")
    banned = set(eye.condition_ids) | {
        "cataract",
        "conjunctivitis",
        "cornea",
        "pupil",
        "red_reflex",
        "va_left",
        "va_right",
    }
    offenders = []
    for path in (REPO_ROOT / "backend" / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in banned - {"normal"}:
            if re.search(rf"\b{re.escape(word)}\b", text):
                offenders.append(f"{path.name}: {word}")
    assert not offenders, offenders


def test_ml_pipeline_cannot_read_app_photo_storage():
    """A.2: no code path copies app photos into training data."""
    sources = [REPO_ROOT / "ml" / "src", REPO_ROOT / "eval"]
    patterns = [
        r"encounter-photos",
        r"^\s*(from|import)\s+app\b",
        r"STORAGE_BUCKET",
        r"local_storage",
        r"\bboto3\b",
    ]
    hits = []
    for path in (p for d in sources for p in d.rglob("*.py") if ".venv" not in p.parts):
        text = path.read_text(encoding="utf-8")
        hits += [f"{path.relative_to(REPO_ROOT)}: {p}" for p in patterns if re.search(p, text, re.MULTILINE)]
    assert not hits, hits


def test_photo_model_has_no_image_column():
    """A.2: database (and its backups) never contain photos."""
    from sqlalchemy import LargeBinary

    from app.core.db import Base

    for table in Base.metadata.tables.values():
        for col in table.columns:
            assert not isinstance(col.type, LargeBinary), f"{table.name}.{col.name}"


def test_storage_keys_live_outside_ml_data():
    assert not (Path(REPO_ROOT / "ml" / "data") / "encounter-photos").exists()
