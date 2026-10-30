"""Mobile assist API: stateless, authorized by a clinic access code (header X-Clinic-Code)."""

import json

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.packs import pack_out
from app.core.db import get_db
from app.core.errors import not_found, unprocessable
from app.modules.assist import service as svc
from app.modules.assist.models import AccessCode
from app.modules.packs.loader import Pack, get_packs

router = APIRouter(prefix="/assist", tags=["assist"])

MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTOS = 8


def clinic_code(
    x_clinic_code: str | None = Header(default=None), db: Session = Depends(get_db)
) -> AccessCode:
    code = svc.check_code(db, x_clinic_code)
    if code is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing clinic access code")
    return code


def active_pack(pack_id: str | None = None) -> Pack:
    packs = [p for p in get_packs().values() if not p.placeholder]
    pack = next((p for p in packs if p.id == pack_id), None) if pack_id else (packs[0] if packs else None)
    if pack is None:
        raise not_found("Pack not available")
    return pack


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise unprocessable("Photo is larger than 15 MB")
    return data


@router.get("/config")
def config(
    profession: str | None = None, code: AccessCode = Depends(clinic_code), pack: Pack = Depends(active_pack)
) -> dict:
    return {"clinic": code.label, "pack": pack_out(pack, profession)}


@router.post("/quality")
async def quality(
    view: str = Form(...),
    file: UploadFile = File(...),
    code: AccessCode = Depends(clinic_code),
    pack: Pack = Depends(active_pack),
) -> dict:
    return svc.quality(pack, view, await _read(file))


@router.post("/analyze")
async def analyze(
    views: list[str] = Form(default=[]),
    photos: list[UploadFile] = File(default=[]),
    answers: str = Form("{}"),
    age: int | None = Form(None, ge=0, le=130),
    sex: str | None = Form(None, pattern="^(male|female|other)$"),
    code: AccessCode = Depends(clinic_code),
    pack: Pack = Depends(active_pack),
    db: Session = Depends(get_db),
) -> dict:
    if len(views) != len(photos):
        raise unprocessable("Each photo needs a view")
    if len(photos) > MAX_PHOTOS:
        raise unprocessable(f"At most {MAX_PHOTOS} photos")
    try:
        parsed = json.loads(answers)
        assert isinstance(parsed, dict)
    except (ValueError, AssertionError):
        raise unprocessable("answers must be a JSON object") from None
    data = [(v, await _read(f)) for v, f in zip(views, photos, strict=True)]
    return svc.analyze(db, pack, data, parsed, age, sex)


@router.post("/quick")
async def quick(
    photos: list[UploadFile] = File(...),
    lighting: list[str] = Form(default=[]),
    answers: str = Form("{}"),
    age: int | None = Form(None, ge=0, le=130),
    sex: str | None = Form(None, pattern="^(male|female|other)$"),
    code: AccessCode = Depends(clinic_code),
    pack: Pack = Depends(active_pack),
    db: Session = Depends(get_db),
) -> dict:
    """Upload photo(s), get the AI ranking with explanations right away."""
    if not photos or len(photos) > MAX_PHOTOS:
        raise unprocessable(f"Send 1 to {MAX_PHOTOS} photos")
    tags = lighting or ["normal"] * len(photos)
    allowed = set(pack.capture_protocol.lighting_views) if pack.capture_protocol else set()
    if len(tags) != len(photos) or any(t not in allowed for t in tags):
        raise unprocessable(f"lighting must be one of {sorted(allowed)} for each photo")
    try:
        parsed = json.loads(answers)
        assert isinstance(parsed, dict)
    except (ValueError, AssertionError):
        raise unprocessable("answers must be a JSON object") from None
    data = [(t, await _read(f)) for t, f in zip(tags, photos, strict=True)]
    return svc.quick(db, pack, data, tags, parsed, age, sex)


@router.post("/explain")
def explain(
    body: svc.ExplainIn, code: AccessCode = Depends(clinic_code), pack: Pack = Depends(active_pack)
) -> dict:
    """Follow-up answers -> refreshed explanation and red flags (the AI ranking itself does not change)."""
    return svc.explain(pack, body)


@router.post("/confirm")
def confirm(
    body: svc.ConfirmIn,
    code: AccessCode = Depends(clinic_code),
    pack: Pack = Depends(active_pack),
    db: Session = Depends(get_db),
) -> dict:
    return svc.confirm(db, pack, code, body)


@router.post("/reveal")
def reveal(
    body: svc.RevealIn,
    code: AccessCode = Depends(clinic_code),
    pack: Pack = Depends(active_pack),
    db: Session = Depends(get_db),
) -> dict:
    return svc.reveal(db, pack, code, body)


@router.post("/outcome")
def outcome(
    body: svc.OutcomeIn, code: AccessCode = Depends(clinic_code), db: Session = Depends(get_db)
) -> dict:
    return svc.outcome(db, code, body)


@router.post("/report")
def report(
    body: svc.ReportIn, code: AccessCode = Depends(clinic_code), pack: Pack = Depends(active_pack)
) -> dict:
    return svc.report(pack, body)
