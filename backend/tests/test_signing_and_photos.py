"""A.2: only clinicians sign; signed reports locked; photos deleted after sign-off / draft expiry; metadata stripped."""

import base64
import io
from datetime import timedelta

from PIL import Image

from app.core.db import utcnow
from app.modules.audit.models import AuditLog
from app.modules.encounters.models import Encounter, Photo
from app.modules.encounters.service import run_photo_retention
from tests.conftest import BASE_EXAM, ack_all, assess, auth, draft, full_encounter, jpeg, start_encounter


def _signed_encounter(client, user):
    enc = full_encounter(client, user)
    ack_all(client, user, enc["id"])
    assess(client, user, enc["id"])
    note = draft(client, user, enc["id"])
    handout = draft(client, user, enc["id"], "patient_handout", "fil")
    r = client.post(
        f"/v1/encounters/{enc['id']}/sign-off",
        json={"report_ids": [note["id"], handout["id"]]},
        headers=auth(user),
    )
    assert r.status_code == 200, r.text
    return enc, r.json()


def test_only_clinicians_sign(client, org_a):
    enc = full_encounter(client, org_a.clinician)
    assess(client, org_a.clinician, enc["id"])
    note = draft(client, org_a.clinician, enc["id"])
    for user in (org_a.staff, org_a.admin):
        r = client.post(
            f"/v1/encounters/{enc['id']}/sign-off", json={"report_ids": [note["id"]]}, headers=auth(user)
        )
        assert r.status_code == 403
        assert client.post(f"/v1/reports/{note['id']}/sign", headers=auth(user)).status_code == 403
        r = client.put(
            f"/v1/encounters/{enc['id']}/assessment",
            json={"diagnoses": [{"condition_id": "normal"}], "urgency": "routine"},
            headers=auth(user),
        )
        assert r.status_code == 403


def test_signed_reports_locked_and_amended(client, org_a):
    _, result = _signed_encounter(client, org_a.clinician)
    rid = result["reports"][0]["id"]
    h = auth(org_a.clinician)
    assert client.patch(f"/v1/reports/{rid}", json={"content": "changed"}, headers=h).status_code == 409
    assert client.post(f"/v1/reports/{rid}/sign", headers=h).status_code == 409
    add = client.post(f"/v1/reports/{rid}/addenda", json={"content": "VA rechecked: 6/9"}, headers=h)
    assert add.status_code == 200
    assert add.json()["parent_report_id"] == rid
    signed = client.post(f"/v1/reports/{add.json()['id']}/sign", headers=h)
    assert signed.status_code == 200, signed.text
    assert client.get(f"/v1/reports/{rid}", headers=h).json()["content"] != "changed"


def test_photos_deleted_after_sign_off(client, db, storage, org_a):
    enc, result = _signed_encounter(client, org_a.clinician)
    photos = db.query(Photo).filter_by(encounter_id=enc["id"]).all()
    assert photos and all(p.deleted_at for p in photos)
    assert not any(storage.exists(p.storage_key) for p in photos)
    assert result["photos_deleted"] is True
    assert result["encounter_status"] == "signed"

    # PDF delivered at sign-off contains the photos; later server PDFs are text only.
    at_signoff = base64.b64decode(result["reports"][0]["pdf_base64"])
    later = client.get(f"/v1/reports/{result['reports'][0]['id']}/pdf", headers=auth(org_a.clinician))
    assert later.status_code == 200
    assert at_signoff.count(b"/Subtype /Image") >= 2
    assert later.content.count(b"/Subtype /Image") == 0

    log = db.query(AuditLog).filter_by(entity_type="photos", entity_id=enc["id"], action="delete").one()
    assert log.detail["reason"] == "signed"


def test_unsigned_draft_photos_expire(client, db, storage, org_a):
    enc = start_encounter(client, org_a.clinician)
    client.post(
        f"/v1/encounters/{enc['id']}/photos",
        data={"view": "right_eye"},
        files={"file": ("e.jpg", jpeg(), "image/jpeg")},
        headers=auth(org_a.clinician),
    )
    row = db.get(Encounter, enc["id"])
    row.created_at = utcnow() - timedelta(hours=73)
    db.commit()

    result = run_photo_retention(db, storage)
    assert result["expired"] == 1
    db.refresh(row)
    assert row.status == "expired"
    photo = db.query(Photo).filter_by(encounter_id=enc["id"]).one()
    assert photo.deleted_at and not storage.exists(photo.storage_key)
    assert db.query(AuditLog).filter_by(entity_type="photos", action="delete").count() == 1


def test_recent_drafts_keep_photos(client, db, storage, org_a):
    enc = full_encounter(client, org_a.clinician)
    assert run_photo_retention(db, storage)["expired"] == 0
    assert db.get(Encounter, enc["id"]).status == "draft"


def test_photo_metadata_stripped(client, db, storage, org_a):
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {1: "N", 2: (14.0, 35.0, 0.0)}  # GPS
    enc = start_encounter(client, org_a.clinician)
    r = client.post(
        f"/v1/encounters/{enc['id']}/photos",
        data={"view": "right_eye"},
        files={"file": ("e.jpg", jpeg(exif=exif.tobytes()), "image/jpeg")},
        headers=auth(org_a.clinician),
    )
    assert r.status_code == 200
    stored = storage.get(db.get(Photo, r.json()["id"]).storage_key)
    img = Image.open(io.BytesIO(stored))
    assert not img.getexif()
    assert "exif" not in img.info and b"PhoneMaker" not in stored


def test_quality_check_flags_blur(client, org_a):
    enc = start_encounter(client, org_a.clinician)
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 90, 90)).save(buf, format="JPEG")
    r = client.post(
        f"/v1/encounters/{enc['id']}/photos",
        data={"view": "right_eye"},
        files={"file": ("flat.jpg", buf.getvalue(), "image/jpeg")},
        headers=auth(org_a.clinician),
    )
    q = r.json()["quality"]
    assert not q["ok"]
    blurry = next(i for i in q["issues"] if i["code"] == "blurry")
    assert blurry["tip"]["en"] and blurry["tip"]["fil"]


def test_signed_url_expires(client, org_a, storage):
    enc = full_encounter(client, org_a.clinician)
    detail = client.get(f"/v1/encounters/{enc['id']}", headers=auth(org_a.clinician)).json()
    url = detail["photos"][0]["url"]
    assert "sig=" in url and "expires=" in url
    assert client.get(url).status_code == 200
    tampered = url.replace("sig=", "sig=0")
    assert client.get(tampered).status_code == 403


def test_encounter_requires_consent(client, org_a):
    h = auth(org_a.clinician)
    pid = client.post("/v1/patients", json={"full_name": "No Consent"}, headers=h).json()["id"]
    r = client.post("/v1/encounters", json={"patient_id": pid, "pack_id": "eye"}, headers=h)
    assert r.status_code == 409


def test_exam_rejects_unknown_fields_and_values(client, org_a):
    enc = start_encounter(client, org_a.clinician)
    h = auth(org_a.clinician)
    assert (
        client.put(f"/v1/encounters/{enc['id']}/exam", json={"answers": {"nope": 1}}, headers=h).status_code
        == 422
    )
    bad = {**BASE_EXAM, "pain_severity": "extreme"}
    assert client.put(f"/v1/encounters/{enc['id']}/exam", json={"answers": bad}, headers=h).status_code == 422
    bad_va = {**BASE_EXAM, "va_right": "great"}
    assert (
        client.put(f"/v1/encounters/{enc['id']}/exam", json={"answers": bad_va}, headers=h).status_code == 422
    )
