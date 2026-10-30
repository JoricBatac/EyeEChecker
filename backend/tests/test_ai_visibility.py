"""A.2: shadow never shown; reveal_after only after the pre-reveal assessment; visible only for visible conditions."""

import json

from app.modules.packs.loader import get_pack
from tests.conftest import BASE_EXAM, assess, auth, full_encounter, set_state

PACK = get_pack("eye")


def _condition_ids_in(payload) -> set[str]:
    text = json.dumps(payload)
    return {cid for cid in PACK.classifiable_ids if f'"{cid}"' in text}


def test_shadow_never_returned_to_clinic_roles(client, db, org_a):
    set_state(db, "shadow")
    enc = full_encounter(client, org_a.clinician)
    assert enc["analysis"]["ai"]["suggestions"] == []
    assert not enc["analysis"]["ai"]["compare_after_assessment"]
    assert assess(client, org_a.clinician, enc["id"]).status_code == 200

    for user in (org_a.clinician, org_a.staff, org_a.admin):
        detail = client.get(f"/v1/encounters/{enc['id']}", headers=auth(user)).json()
        assert detail["ai"]["suggestions"] == []
        assert "probabilities" not in json.dumps(detail)
    compare = client.get(f"/v1/encounters/{enc['id']}/ai-compare", headers=auth(org_a.clinician)).json()
    assert compare["suggestions"] == []


def test_reveal_after_withheld_until_assessment(client, db, org_a):
    set_state(db, "reveal_after")
    enc = full_encounter(client, org_a.clinician)
    assert enc["analysis"]["ai"]["suggestions"] == []
    assert enc["analysis"]["ai"]["compare_after_assessment"] is True

    r = client.get(f"/v1/encounters/{enc['id']}/ai-compare", headers=auth(org_a.clinician))
    assert r.status_code == 409

    assert assess(client, org_a.clinician, enc["id"], "conj_viral").status_code == 200
    r = client.get(f"/v1/encounters/{enc['id']}/ai-compare", headers=auth(org_a.clinician))
    assert r.status_code == 200
    assert len(r.json()["suggestions"]) == 3
    assert r.json()["label"] == "AI suggestion, for clinician review"


def test_pre_reveal_assessment_cannot_be_overwritten(client, db, org_a):
    set_state(db, "reveal_after")
    enc = full_encounter(client, org_a.clinician)
    assess(client, org_a.clinician, enc["id"], "conj_viral")
    client.get(f"/v1/encounters/{enc['id']}/ai-compare", headers=auth(org_a.clinician))
    assess(client, org_a.clinician, enc["id"], "conj_allergic")

    detail = client.get(f"/v1/encounters/{enc['id']}", headers=auth(org_a.clinician)).json()
    assert detail["pre_reveal_assessment"]["diagnoses"][0]["condition_id"] == "conj_viral"
    assert detail["assessment"]["phase"] == "post_reveal"
    assert detail["assessment"]["diagnoses"][0]["condition_id"] == "conj_allergic"
    assert detail["assessment"]["changed_after_reveal"] is True


def test_visible_returns_only_visible_conditions(client, db, org_a):
    set_state(db, "shadow")
    visible = ["normal", "conj_viral", "dry_eye"]
    set_state(db, "visible", visible, org_id=org_a.org.id)
    enc = full_encounter(client, org_a.clinician)
    suggestions = enc["analysis"]["ai"]["suggestions"]
    assert {s["condition_id"] for s in suggestions} == set(visible)
    assert _condition_ids_in(enc["analysis"]["ai"]) <= set(visible)
    for s in suggestions:
        assert s["likelihood"] in {"high", "moderate", "low"}


def test_mixed_states_compare_excludes_shadow(client, db, org_a):
    set_state(db, "shadow")
    set_state(db, "reveal_after", ["conj_viral", "conj_bacterial"], org_id=org_a.org.id)
    set_state(db, "visible", ["normal"], org_id=org_a.org.id)
    enc = full_encounter(client, org_a.clinician)
    assert {s["condition_id"] for s in enc["analysis"]["ai"]["suggestions"]} == {"normal"}
    assess(client, org_a.clinician, enc["id"])
    compare = client.get(f"/v1/encounters/{enc['id']}/ai-compare", headers=auth(org_a.clinician)).json()
    assert {s["condition_id"] for s in compare["suggestions"]} <= {"normal", "conj_viral", "conj_bacterial"}


def test_state_scoped_to_org(client, db, org_a, org_b):
    set_state(db, "shadow")
    set_state(db, "visible", ["normal"], org_id=org_a.org.id)
    a = full_encounter(client, org_a.clinician)
    b = full_encounter(client, org_b.clinician)
    assert a["analysis"]["ai"]["suggestions"]
    assert b["analysis"]["ai"]["suggestions"] == []


def test_visible_requires_advisor_signoff(client, internal):
    h = auth(internal["admin"])
    r = client.put("/v1/internal/packs/eye/conditions/normal/state", json={"state": "visible"}, headers=h)
    assert r.status_code == 422
    r = client.put(
        "/v1/internal/packs/eye/conditions/normal/state",
        json={"state": "visible", "advisor_signoff": "Dr. Advisor, 2026-10-30, metrics v1"},
        headers=h,
    )
    assert r.status_code == 200
    reviewer = client.put(
        "/v1/internal/packs/eye/conditions/normal/state",
        json={"state": "off"},
        headers=auth(internal["reviewer"]),
    )
    assert reviewer.status_code == 403


def test_feedback_requires_shown_ai(client, db, org_a):
    set_state(db, "shadow")
    enc = full_encounter(client, org_a.clinician, BASE_EXAM)
    r = client.post(
        f"/v1/encounters/{enc['id']}/feedback", json={"rating": "correct"}, headers=auth(org_a.clinician)
    )
    assert r.status_code == 409
