"""A.2: users can never read or write another organization's data."""

from tests.conftest import ack_all, assess, auth, draft, full_encounter


def test_other_org_cannot_reach_any_record(client, org_a, org_b):
    enc = full_encounter(client, org_a.clinician)
    eid, pid = enc["id"], enc["patient"]["id"]
    ack_all(client, org_a.clinician, eid)
    assess(client, org_a.clinician, eid)
    report = draft(client, org_a.clinician, eid)
    photo_id = client.get(f"/v1/encounters/{eid}", headers=auth(org_a.clinician)).json()["photos"][0]["id"]

    h = auth(org_b.clinician)
    attempts = [
        ("get", f"/v1/patients/{pid}", None),
        ("post", f"/v1/patients/{pid}/consents", {"version": "v1", "granted": True}),
        ("post", "/v1/encounters", {"patient_id": pid, "pack_id": "eye"}),
        ("get", f"/v1/encounters/{eid}", None),
        ("put", f"/v1/encounters/{eid}/exam", {"answers": {}}),
        ("post", f"/v1/encounters/{eid}/analyze", None),
        ("get", f"/v1/encounters/{eid}/ai-compare", None),
        (
            "put",
            f"/v1/encounters/{eid}/assessment",
            {"diagnoses": [{"condition_id": "normal"}], "urgency": "routine"},
        ),
        ("post", f"/v1/encounters/{eid}/reports", {"type": "exam_note"}),
        ("post", f"/v1/encounters/{eid}/sign-off", {"report_ids": [report["id"]]}),
        ("post", f"/v1/encounters/{eid}/feedback", {"rating": "correct"}),
        ("patch", f"/v1/encounters/{eid}/photos/{photo_id}", {"quality_override_reason": "fine"}),
        ("delete", f"/v1/encounters/{eid}/photos/{photo_id}", None),
        ("get", f"/v1/reports/{report['id']}", None),
        ("patch", f"/v1/reports/{report['id']}", {"content": "hacked"}),
        ("get", f"/v1/reports/{report['id']}/pdf", None),
        ("post", f"/v1/reports/{report['id']}/sign", None),
        ("post", f"/v1/reports/{report['id']}/polish", None),
    ]
    for method, url, body in attempts:
        kwargs = {"headers": h}
        if body is not None:
            kwargs["json"] = body
        r = getattr(client, method)(url, **kwargs)
        assert r.status_code == 404, f"{method.upper()} {url} -> {r.status_code}"

    # Upload into another org's encounter
    r = client.post(
        f"/v1/encounters/{eid}/photos",
        data={"view": "right_eye"},
        files={"file": ("x.jpg", b"x", "image/jpeg")},
        headers=h,
    )
    assert r.status_code == 404


def test_lists_only_show_own_org(client, org_a, org_b):
    full_encounter(client, org_a.clinician)
    h = auth(org_b.clinician)
    assert client.get("/v1/patients", headers=h).json() == []
    assert client.get("/v1/encounters", headers=h).json() == []
    assert client.get("/v1/referrals", headers=h).json() == []


def test_org_admin_cannot_manage_other_org_users(client, org_a, org_b):
    r = client.patch(
        f"/v1/org/users/{org_a.clinician.id}", json={"is_active": False}, headers=auth(org_b.admin)
    )
    assert r.status_code == 404


def test_internal_roles_cannot_use_clinic_endpoints(client, org_a, internal):
    enc = full_encounter(client, org_a.clinician)
    for role in ("admin", "reviewer"):
        h = auth(internal[role])
        assert client.get(f"/v1/encounters/{enc['id']}", headers=h).status_code == 403
        assert client.get("/v1/patients", headers=h).status_code == 403


def test_clinic_roles_cannot_use_internal_endpoints(client, org_a):
    for user in (org_a.clinician, org_a.admin):
        assert client.get("/v1/internal/review-queue", headers=auth(user)).status_code == 403
        r = client.put(
            "/v1/internal/packs/eye/conditions/normal/state", json={"state": "visible"}, headers=auth(user)
        )
        assert r.status_code == 403
