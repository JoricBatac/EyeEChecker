"""Stateless mobile assist mode: nothing about the patient is stored, AI hidden until the clinician's pick."""

import json

import pytest
from sqlalchemy import inspect

from app.core.db import engine
from app.modules.assist.models import AccessCode, AssistScore
from app.modules.assist.service import hash_code
from app.modules.packs.loader import get_pack
from tests.conftest import BASE_EXAM, jpeg, set_state

PACK = get_pack("eye")
CODE = "TEST-CODE-0001"


@pytest.fixture
def code(db):
    row = AccessCode(label="Partner A", code_hash=hash_code(CODE))
    db.add(row)
    db.commit()
    return row


H = {"X-Clinic-Code": CODE}


def analyze(client, exam=None, age=40, views=("right_eye", "left_eye")):
    files = [("photos", (f"{v}.jpg", jpeg(i + 1), "image/jpeg")) for i, v in enumerate(views)]
    data = {"views": list(views), "answers": json.dumps(exam or BASE_EXAM), "age": str(age), "sex": "female"}
    r = client.post("/v1/assist/analyze", data=data, files=files, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def reveal(client, token, cid="conj_viral", side="right", urgency="routine"):
    body = {"analysis_token": token, "diagnoses": [{"condition_id": cid, "side": side}], "urgency": urgency}
    return client.post("/v1/assist/reveal", json=body, headers=H)


def ack_keys(alerts):
    return [a["key"] for a in alerts]


def report(client, token, alerts, cid="conj_viral", side="right", **extra):
    body = {
        "analysis_token": token,
        "report_type": "patient_handout",
        "locale": "fil",
        "diagnoses": [{"condition_id": cid, "side": side}],
        "urgency": "routine",
        "acknowledged": ack_keys(alerts),
        "clinician_name": "Dr. Santos",
        "clinic_name": "Clinic A",
        **extra,
    }
    return client.post("/v1/assist/report", json=body, headers=H)


def table_counts() -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t: conn.exec_driver_sql(f"SELECT COUNT(*) FROM {t}").scalar()
            for t in inspect(engine).get_table_names()
        }


def test_requires_valid_clinic_code(client, code, db):
    assert client.get("/v1/assist/config").status_code == 401
    assert client.get("/v1/assist/config", headers={"X-Clinic-Code": "WRONG"}).status_code == 401
    r = client.get("/v1/assist/config", headers=H)
    assert r.status_code == 200 and r.json()["clinic"] == "Partner A"
    code.active = False
    db.commit()
    assert client.get("/v1/assist/config", headers=H).status_code == 401


def test_code_is_case_insensitive(client, code):
    assert client.get("/v1/assist/config", headers={"X-Clinic-Code": CODE.lower()}).status_code == 200


def test_analyze_stores_nothing_and_hides_ai(client, code):
    before = table_counts()
    result = analyze(client)
    after = table_counts()
    changed = {t for t in before if before[t] != after[t]}
    assert changed == set(), changed  # no photo, patient, exam or score rows
    assert result["ai_available"] is True
    text = json.dumps({k: v for k, v in result.items() if k != "analysis_token"})
    assert "probab" not in text
    for cid in PACK.classifiable_ids:
        assert f'"{cid}"' not in text


def test_token_is_opaque(client, code):
    token = analyze(client)["analysis_token"]
    import base64

    raw = base64.urlsafe_b64decode(token + "==")
    for needle in (b"probabilities", b"conj_viral", b"female", b"redness"):
        assert needle not in raw


def test_tampered_token_rejected(client, code):
    token = analyze(client)["analysis_token"]
    bad = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]
    assert reveal(client, bad).status_code == 409


def test_reveal_logs_pre_ai_pick_once(client, code, db):
    token = analyze(client)["analysis_token"]
    r = reveal(client, token, "conj_viral")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["suggestions"]) == 3
    assert body["label"] == "AI suggestion, for clinician review"
    # A second reveal with a different pick must not overwrite the first impression.
    reveal(client, token, "dry_eye")
    rows = db.query(AssistScore).all()
    assert len(rows) == 1 and rows[0].clinician_dx == ["conj_viral"]

    client.post(
        "/v1/assist/outcome",
        json={"analysis_token": token, "final_diagnoses": ["conj_allergic"], "rating": "wrong_cause"},
        headers=H,
    )
    db.refresh(rows[0])
    assert rows[0].changed_after_reveal is True and rows[0].rating == "wrong_cause"


def test_score_row_has_no_identifiers(client, code, db):
    exam = {**BASE_EXAM, "notes": "Lives at 12 Mabini St"}
    token = analyze(client, exam)["analysis_token"]
    reveal(client, token)
    row = db.query(AssistScore).one()
    dumped = json.dumps({c.name: getattr(row, c.name) for c in row.__table__.columns}, default=str)
    for secret in ("Mabini", "female", "redness", "right"):
        assert secret not in dumped
    assert row.age_band == "adult"


def test_shadow_never_revealed(client, code, db):
    set_state(db, "shadow")
    set_state(db, "reveal_after", ["normal", "dry_eye"])
    token = analyze(client)["analysis_token"]
    ids = {s["condition_id"] for s in reveal(client, token).json()["suggestions"]}
    assert ids <= {"normal", "dry_eye"}


def test_visible_still_waits_for_pick(client, code, db):
    set_state(db, "visible")
    result = analyze(client)
    assert "suggestions" not in result
    assert reveal(client, result["analysis_token"]).json()["suggestions"]


@pytest.mark.parametrize("state", ["off", "shadow", "reveal_after", "visible"])
def test_red_flags_and_pediatric_rule_every_state(client, code, db, state):
    set_state(db, state)
    result = analyze(client, {**BASE_EXAM, "trauma_or_chemical": "chemical", "red_reflex": "white"}, age=5)
    rules = {a["rule_id"] for a in result["red_flags"]}
    assert {"chemical_or_trauma", "pediatric_abnormal_reflex"} <= rules
    assert result["suggested_urgency"] == "urgent"


def test_report_requires_acknowledged_red_flags(client, code):
    result = analyze(client, {**BASE_EXAM, "pain_severity": "severe"})
    token = result["analysis_token"]
    revealed = reveal(client, token).json()
    assert report(client, token, []).status_code == 422
    r = report(client, token, revealed["red_flags"])
    assert r.status_code == 200, r.text


def test_report_has_placeholder_not_name(client, code):
    token = analyze(client)["analysis_token"]
    r = report(client, token, reveal(client, token).json()["red_flags"])
    content = r.json()["content"]
    assert "{{PATIENT_NAME}}" in content
    assert "Resulta" in content  # Filipino template
    assert "Dr. Santos" in content


def test_cataract_report_needs_visual_acuity_and_refers(client, code):
    token = analyze(client, {**BASE_EXAM, "affected_side": "left"}, age=70)["analysis_token"]
    alerts = reveal(client, token, "lens_opacity_cataract", "left").json()["red_flags"]
    r = report(client, token, alerts, cid="lens_opacity_cataract", side="left")
    assert r.status_code == 422 and any("va_left" in p for p in r.json()["detail"])

    exam = {**BASE_EXAM, "affected_side": "left", "va_left": "6/36"}
    token = analyze(client, exam, age=70)["analysis_token"]
    alerts = reveal(client, token, "lens_opacity_cataract", "left").json()["red_flags"]
    r = report(
        client,
        token,
        alerts,
        cid="lens_opacity_cataract",
        side="left",
        report_type="referral_letter",
        locale="en",
    )
    assert r.status_code == 200, r.text
    assert r.json()["referral_reasons"] == ["Needs evaluation for cataract surgery"]


def test_cataract_pick_requests_extra_views(client, code):
    token = analyze(client, age=70)["analysis_token"]
    views = reveal(client, token, "lens_opacity_cataract", "left").json()["required_views"]
    assert {"dim_light", "red_reflex_flash"} <= set(views)


def test_scope_of_practice_in_reports(client, code):
    token = analyze(client)["analysis_token"]
    alerts = reveal(client, token, "conj_bacterial").json()["red_flags"]
    r = report(
        client,
        token,
        alerts,
        cid="conj_bacterial",
        plan_items=["topical_antibiotic"],
        profession="optometrist",
    )
    assert r.status_code == 422


def test_quality_check_stores_nothing(client, code, storage):
    before = table_counts()
    r = client.post(
        "/v1/assist/quality",
        data={"view": "right_eye"},
        files={"file": ("e.jpg", jpeg(), "image/jpeg")},
        headers=H,
    )
    assert r.status_code == 200 and "ok" in r.json()
    assert table_counts() == before


# ---------- quick flow: photo in, explained ranking out ----------


def quick(client, exam=None, lighting=("normal",), age=60):
    files = [("photos", (f"p{i}.jpg", jpeg(i + 1), "image/jpeg")) for i in range(len(lighting))]
    data = {"lighting": list(lighting), "answers": json.dumps(exam or {}), "age": str(age)}
    r = client.post("/v1/assist/quick", data=data, files=files, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_quick_needs_only_a_photo(client, code):
    files = [("photos", ("p.jpg", jpeg(1), "image/jpeg"))]
    r = client.post("/v1/assist/quick", files=files, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == 3
    assert body["label"] == "AI suggestion, for clinician review"
    assert body["confidence"] in {"clear", "split", "low"}
    for res in body["results"]:
        assert res["visual_features"]["en"] and "probability" in res


def test_quick_stores_nothing(client, code):
    before = table_counts()
    quick(client, BASE_EXAM)
    assert table_counts() == before


def test_quick_explains_with_exam_answers(client, code):
    exam = {
        **BASE_EXAM,
        "vision_change": "gradual_reduction",
        "va_right": "6/36",
        "va_left": "6/9",
        "red_reflex": "dull",
    }
    from app.modules.assist import service

    pack = PACK
    facts = {"exam.vision_change": "gradual_reduction", "exam.red_reflex": "dull", "patient.age": 70}
    why = service._explain(pack, "lens_opacity_cataract", 0.5, facts)
    assert len(why["supports"]) == 3 and why["against"] == []
    body = quick(client, exam, age=70)
    assert body["answered_questions"] > 0


def test_quick_lighting_tags(client, code):
    body = quick(client, lighting=("dim", "flash"))
    assert [p["lighting"] for p in body["photos"]] == ["dim", "flash"]
    files = [("photos", ("p.jpg", jpeg(1), "image/jpeg"))]
    r = client.post("/v1/assist/quick", data={"lighting": ["infrared"]}, files=files, headers=H)
    assert r.status_code == 422


def test_quick_never_shows_shadow(client, code, db):
    set_state(db, "shadow")
    set_state(db, "reveal_after", ["normal"])
    body = quick(client)
    assert [r["condition_id"] for r in body["results"]] == ["normal"]


def test_quick_red_flags_still_fire(client, code):
    body = quick(client, {**BASE_EXAM, "trauma_or_chemical": "chemical"})
    assert "chemical_or_trauma" in {a["rule_id"] for a in body["red_flags"]}
    assert body["suggested_urgency"] == "urgent"


def test_confirm_logs_ai_first_score(client, code, db):
    token = quick(client)["analysis_token"]
    r = client.post(
        "/v1/assist/confirm",
        json={
            "analysis_token": token,
            "diagnoses": [{"condition_id": "dry_eye"}],
            "urgency": "routine",
            "rating": "correct",
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    row = db.query(AssistScore).one()
    assert row.mode == "quick" and row.clinician_dx == ["dry_eye"] and row.rating == "correct"


# ---------- follow-up questions: chosen per photo, refine the explanation only ----------


def test_quick_suggests_follow_up_questions(client, code):
    body = quick(client)
    fu = body["follow_up"]
    assert 1 <= len(fu) <= 4
    askable = {f.id for f in PACK.exam_form.fields if not f.free_text} | {"age"}
    assert set(fu) <= askable
    assert "notes" not in fu  # free text is never asked


def test_follow_up_targets_top_suggestions():
    from app.modules.assist.service import follow_up_questions

    results = [
        {"condition_id": "lens_opacity_cataract", "probability": 0.5},
        {"condition_id": "uveitis", "probability": 0.3},
    ]
    fu = follow_up_questions(PACK, results, {}, None)
    assert {"vision_change", "pain_severity"} & set(fu)
    assert "discharge_type" not in fu[:2]
    answered = follow_up_questions(PACK, results, {"vision_change": "none", "pain_severity": "none"}, 60)
    assert "vision_change" not in answered and "pain_severity" not in answered and "age" not in answered


def test_explain_updates_reasons_not_ranking(client, code):
    first = quick(client)
    token = first["analysis_token"]
    r = client.post(
        "/v1/assist/explain",
        json={
            "analysis_token": token,
            "answers": {"trauma_or_chemical": "chemical", "symptoms": ["photophobia"]},
            "age": 40,
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["probability"] for x in body["results"]] == [x["probability"] for x in first["results"]]
    assert "chemical_or_trauma" in {a["rule_id"] for a in body["red_flags"]}
    assert body["answered_questions"] == 3
    assert "trauma_or_chemical" not in body["follow_up"] and "age" not in body["follow_up"]


def test_explain_stores_nothing_and_rejects_bad_answers(client, code):
    token = quick(client)["analysis_token"]
    before = table_counts()
    bad = client.post(
        "/v1/assist/explain",
        json={"analysis_token": token, "answers": {"pain_severity": "extreme"}},
        headers=H,
    )
    assert bad.status_code == 422
    ok = client.post(
        "/v1/assist/explain", json={"analysis_token": token, "answers": {"pain_severity": "none"}}, headers=H
    )
    assert ok.status_code == 200
    assert table_counts() == before


def test_quick_returns_top3_and_the_rest(client, code):
    body = quick(client)
    assert len(body["results"]) == 3
    all_ids = [r["condition_id"] for r in body["results"] + body["others"]]
    assert len(all_ids) == len(set(all_ids)) == len(PACK.classifiable_ids)
    probs = [r["probability"] for r in body["results"] + body["others"]]
    assert probs == sorted(probs, reverse=True)


def test_quick_accepts_multiple_photos(client, code):
    body = quick(client, lighting=("normal", "dim", "flash"))
    assert len(body["photos"]) == 3
