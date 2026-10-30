"""A.2: red flags always alert and block sign-off until acknowledged; pediatric reflex; cataract rules."""

import pytest

from tests.conftest import BASE_EXAM, ack_all, assess, auth, draft, full_encounter, set_state

STATES = ["off", "shadow", "reveal_after", "visible"]


def _rule_ids(alerts) -> set[str]:
    return {a["rule_id"] for a in alerts}


@pytest.mark.parametrize("state", STATES)
def test_chemical_exposure_alerts_in_every_state(client, db, org_a, state):
    set_state(db, state)
    if state == "visible":
        set_state(db, "visible", None, org_id=org_a.org.id)
    exam = {**BASE_EXAM, "trauma_or_chemical": "chemical"}
    enc = full_encounter(client, org_a.clinician, exam)
    assert "chemical_or_trauma" in _rule_ids(enc["analysis"]["red_flags"])
    assert enc["analysis"]["suggested_urgency"] == "urgent"


def test_sign_off_blocked_until_acknowledged(client, org_a):
    exam = {**BASE_EXAM, "pain_severity": "severe"}
    enc = full_encounter(client, org_a.clinician, exam)
    assess(client, org_a.clinician, enc["id"], "keratitis_ulcer", urgency="urgent")
    note = draft(client, org_a.clinician, enc["id"])
    r = client.post(
        f"/v1/encounters/{enc['id']}/sign-off",
        json={"report_ids": [note["id"]]},
        headers=auth(org_a.clinician),
    )
    assert r.status_code == 422
    assert any("not acknowledged" in p for p in r.json()["detail"])

    ack_all(client, org_a.clinician, enc["id"])
    r = client.post(
        f"/v1/encounters/{enc['id']}/sign-off",
        json={"report_ids": [note["id"]]},
        headers=auth(org_a.clinician),
    )
    assert r.status_code == 200, r.text


def test_staff_cannot_acknowledge(client, org_a):
    enc = full_encounter(client, org_a.clinician, {**BASE_EXAM, "pain_severity": "severe"})
    alert = enc["analysis"]["red_flags"][0]
    r = client.post(f"/v1/encounters/{enc['id']}/alerts/{alert['id']}/ack", headers=auth(org_a.staff))
    assert r.status_code == 403


@pytest.mark.parametrize("state", STATES)
def test_pediatric_abnormal_reflex_always_urgent_referral(client, db, org_a, state):
    set_state(db, state)
    exam = {**BASE_EXAM, "red_reflex": "white"}
    enc = full_encounter(client, org_a.clinician, exam, age=4)
    alerts = {a["rule_id"]: a for a in enc["analysis"]["red_flags"]}
    assert "pediatric_abnormal_reflex" in alerts
    assert alerts["pediatric_abnormal_reflex"]["severity"] == "urgent"
    assert alerts["pediatric_abnormal_reflex"]["referral"] is True


def test_pediatric_suspected_cataract_triggers_alert_and_urgent_referral(client, org_a):
    exam = {**BASE_EXAM, "vision_change": "gradual_reduction", "va_right": "6/60", "va_left": "6/9"}
    enc = full_encounter(client, org_a.clinician, exam, age=6)
    r = assess(client, org_a.clinician, enc["id"], "lens_opacity_cataract", side="right")
    assert "pediatric_abnormal_reflex" in _rule_ids(r.json()["red_flags"])
    ack_all(client, org_a.clinician, enc["id"])
    note = draft(client, org_a.clinician, enc["id"])
    r = client.post(
        f"/v1/encounters/{enc['id']}/sign-off",
        json={"report_ids": [note["id"]]},
        headers=auth(org_a.clinician),
    )
    assert r.status_code == 200, r.text
    refs = client.get("/v1/referrals", headers=auth(org_a.clinician)).json()
    assert refs[0]["urgency"] == "urgent"


def test_adult_reflex_does_not_trigger_pediatric_rule(client, org_a):
    enc = full_encounter(client, org_a.clinician, {**BASE_EXAM, "red_reflex": "white"}, age=40)
    assert "pediatric_abnormal_reflex" not in _rule_ids(enc["analysis"]["red_flags"])


def test_cataract_requires_visual_acuity_and_creates_referral(client, org_a):
    enc = full_encounter(client, org_a.clinician, {**BASE_EXAM, "affected_side": "left"}, age=70)
    assess(client, org_a.clinician, enc["id"], "lens_opacity_cataract", side="left")
    ack_all(client, org_a.clinician, enc["id"])
    note = draft(client, org_a.clinician, enc["id"])
    h = auth(org_a.clinician)
    r = client.post(f"/v1/encounters/{enc['id']}/sign-off", json={"report_ids": [note["id"]]}, headers=h)
    assert r.status_code == 422
    assert any("va_left" in p for p in r.json()["detail"])

    client.put(
        f"/v1/encounters/{enc['id']}/exam", json={"answers": {**BASE_EXAM, "va_left": "6/36"}}, headers=h
    )
    r = client.post(f"/v1/encounters/{enc['id']}/sign-off", json={"report_ids": [note["id"]]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["referral_id"]
    refs = client.get("/v1/referrals", headers=h).json()
    assert refs[0]["reasons"] == ["Needs evaluation for cataract surgery"]
    assert refs[0]["urgency"] == "routine"


def test_cataract_requires_side(client, org_a):
    enc = full_encounter(client, org_a.clinician, age=70)
    assess(client, org_a.clinician, enc["id"], "lens_opacity_cataract", side=None)
    note = draft(client, org_a.clinician, enc["id"])
    r = client.post(
        f"/v1/encounters/{enc['id']}/sign-off",
        json={"report_ids": [note["id"]]},
        headers=auth(org_a.clinician),
    )
    assert r.status_code == 422
    assert any("Specify the side" in p for p in r.json()["detail"])


def test_suspected_cataract_requires_extra_views(client, org_a):
    enc = full_encounter(client, org_a.clinician, age=70)
    r = assess(client, org_a.clinician, enc["id"], "lens_opacity_cataract", side="left")
    assert {"dim_light", "red_reflex_flash"} <= set(r.json()["required_views"])


class _FixedClassifier:
    kind = "stub"
    model_version = "fixed-1"

    def __init__(self, probabilities):
        self.probabilities = probabilities
        self.condition_ids = list(probabilities)

    def predict(self, images):
        return dict(self.probabilities)


@pytest.fixture
def emergency_model(monkeypatch):
    from app.modules.encounters import service
    from app.modules.packs.loader import get_pack

    ids = get_pack("eye").classifiable_ids
    probs = {cid: 0.02 for cid in ids}
    probs["keratitis_ulcer"] = 1 - 0.02 * (len(ids) - 1)
    monkeypatch.setattr(service, "get_classifier", lambda pack_id: _FixedClassifier(probs))


@pytest.mark.parametrize("state", ["shadow", "reveal_after"])
def test_emergency_model_alert_logged_not_shown_before_assessment(client, db, org_a, emergency_model, state):
    from app.modules.encounters.models import RedFlagAlert

    set_state(db, state)
    enc = full_encounter(client, org_a.clinician)
    row = db.query(RedFlagAlert).filter_by(encounter_id=enc["id"], rule_id="emergency_model").one()
    assert row.subject == "keratitis_ulcer" and not row.shown
    assert "emergency_model" not in _rule_ids(enc["analysis"]["red_flags"])


def test_emergency_model_alert_shown_after_reveal(client, db, org_a, emergency_model):
    set_state(db, "reveal_after")
    enc = full_encounter(client, org_a.clinician)
    assess(client, org_a.clinician, enc["id"], "conj_viral")
    compare = client.get(f"/v1/encounters/{enc['id']}/ai-compare", headers=auth(org_a.clinician)).json()
    assert "emergency_model" in _rule_ids(compare["red_flags"])


def test_emergency_model_alert_shown_when_visible(client, db, org_a, emergency_model):
    set_state(db, "visible")
    enc = full_encounter(client, org_a.clinician)
    assert "emergency_model" in _rule_ids(enc["analysis"]["red_flags"])
    assert enc["analysis"]["suggested_urgency"] == "urgent"
