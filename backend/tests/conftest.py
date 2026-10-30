import io
import os
import tempfile

# Configure before the app is imported: settings and engine are created at import time.
os.environ.update(
    APP_ENV="test",
    DATABASE_URL="sqlite:///:memory:",
    STORAGE_BACKEND="local",
    LOCAL_STORAGE_DIR=tempfile.mkdtemp(prefix="scanassist-test-"),
    CLASSIFIER="stub",
    LLM_PROVIDER="none",
    JWT_SECRET="test-secret-at-least-32-characters-long",
)

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import models  # noqa: E402, F401
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import create_token, hash_password  # noqa: E402
from app.core.storage import get_storage  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.orgs.models import Organization, OrgPack, User  # noqa: E402
from app.modules.packs.loader import get_pack  # noqa: E402
from app.modules.packs.models import ConditionState  # noqa: E402

BASE_EXAM = {
    "affected_side": "right",
    "symptoms": ["redness", "tearing"],
    "duration": "1_3d",
    "pain_severity": "none",
    "vision_change": "none",
    "contact_lens": False,
    "prior_eye_surgery": ["none"],
    "trauma_or_chemical": "none",
}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def storage():
    return get_storage()


class OrgFixture:
    def __init__(self, db, name: str):
        self.org = Organization(name=name, address="Manila")
        db.add(self.org)
        db.flush()
        db.add(OrgPack(org_id=self.org.id, pack_id="eye", enabled=True))

        def user(role, profession=None, email=None):
            u = User(
                org_id=self.org.id,
                email=email or f"{role}-{self.org.id[:6]}@test.ph",
                full_name=f"{role.title()} {name}",
                role=role,
                profession=profession,
                license_no="LIC-1" if role == "clinician" else None,
                password_hash=hash_password("pw-123456"),
            )
            db.add(u)
            return u

        self.clinician = user("clinician", "physician")
        self.optometrist = user("clinician", "optometrist", email=f"optom-{self.org.id[:6]}@test.ph")
        self.staff = user("staff", "nurse")
        self.admin = user("org_admin")
        db.commit()


def auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user.id, 'access', 60)}"}


@pytest.fixture
def org_a(db):
    return OrgFixture(db, "Clinic A")


@pytest.fixture
def org_b(db):
    return OrgFixture(db, "Clinic B")


@pytest.fixture
def internal(db):
    org = Organization(name="Internal", kind="internal", is_internal=True)
    db.add(org)
    db.flush()
    admin = User(org_id=org.id, email="ia@x.dev", full_name="IA", role="internal_admin", password_hash="x")
    reviewer = User(
        org_id=org.id, email="ir@x.dev", full_name="IR", role="internal_reviewer", password_hash="x"
    )
    db.add_all([admin, reviewer])
    db.commit()
    return {"admin": admin, "reviewer": reviewer}


def set_state(db, state: str, conditions: list[str] | None = None, org_id: str | None = None) -> None:
    pack = get_pack("eye")
    for cid in conditions or pack.classifiable_ids:
        db.add(ConditionState(pack_id="eye", condition_id=cid, org_id=org_id, state=state))
    db.commit()


def jpeg(seed: int = 1, size=(800, 600), exif: bytes | None = None) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(60, 200, size=(size[1], size[0], 3), dtype=np.uint8)
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif else {}
    Image.fromarray(arr).save(buf, format="JPEG", **kwargs)
    return buf.getvalue()


def start_encounter(client, user, age: int = 40, consent: bool = True) -> dict:
    h = auth(user)
    p = client.post(
        "/v1/patients", json={"full_name": "Juan Dela Cruz", "age_years": age, "sex": "male"}, headers=h
    )
    assert p.status_code == 200, p.text
    pid = p.json()["id"]
    if consent:
        r = client.post(f"/v1/patients/{pid}/consents", json={"version": "v1", "granted": True}, headers=h)
        assert r.status_code == 200
    e = client.post("/v1/encounters", json={"patient_id": pid, "pack_id": "eye"}, headers=h)
    assert e.status_code == 200, e.text
    return e.json()


def upload(client, user, enc_id: str, view: str = "right_eye", seed: int = 1):
    return client.post(
        f"/v1/encounters/{enc_id}/photos",
        data={"view": view},
        files={"file": ("eye.jpg", jpeg(seed), "image/jpeg")},
        headers=auth(user),
    )


def full_encounter(client, user, exam: dict | None = None, age: int = 40) -> dict:
    """Encounter with photos and exam, analyzed. Returns the encounter JSON plus the analysis."""
    enc = start_encounter(client, user, age=age)
    upload(client, user, enc["id"], "right_eye", 1)
    upload(client, user, enc["id"], "left_eye", 2)
    r = client.put(
        f"/v1/encounters/{enc['id']}/exam", json={"answers": exam or BASE_EXAM}, headers=auth(user)
    )
    assert r.status_code == 200, r.text
    a = client.post(f"/v1/encounters/{enc['id']}/analyze", headers=auth(user))
    assert a.status_code == 200, a.text
    return {**enc, "analysis": a.json()}


def assess(client, user, enc_id: str, condition: str = "conj_viral", side: str | None = "right", **extra):
    body = {
        "diagnoses": [{"condition_id": condition, "side": side}],
        "urgency": "routine",
        "plan": {"items": []},
    }
    body.update(extra)
    return client.put(f"/v1/encounters/{enc_id}/assessment", json=body, headers=auth(user))


def ack_all(client, user, enc_id: str) -> None:
    enc = client.get(f"/v1/encounters/{enc_id}", headers=auth(user)).json()
    for alert in enc["red_flags"]:
        if not alert["acknowledged"]:
            client.post(f"/v1/encounters/{enc_id}/alerts/{alert['id']}/ack", headers=auth(user))


def draft(client, user, enc_id: str, type_: str = "exam_note", locale: str = "en") -> dict:
    r = client.post(
        f"/v1/encounters/{enc_id}/reports", json={"type": type_, "locale": locale}, headers=auth(user)
    )
    assert r.status_code == 200, r.text
    return r.json()
