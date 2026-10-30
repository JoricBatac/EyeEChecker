from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import clinic_user
from app.core.db import get_db
from app.core.errors import not_found
from app.modules.audit.service import audit
from app.modules.encounters.models import Encounter
from app.modules.orgs.models import Site, User
from app.modules.patients.models import Consent, Patient

router = APIRouter(prefix="/patients", tags=["patients"])

CARE_CONSENT = "care_documentation"


class PatientIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    birth_date: date | None = None
    age_years: int | None = Field(default=None, ge=0, le=130)
    sex: str | None = Field(default=None, pattern="^(male|female|other)$")
    contact: str | None = None
    clinic_ref: str | None = None
    site_id: str | None = None


class ConsentIn(BaseModel):
    consent_type: str = CARE_CONSENT
    version: str
    granted: bool


def patient_out(p: Patient, consents: list[Consent] | None = None) -> dict:
    out: dict[str, Any] = {
        "id": p.id,
        "full_name": p.full_name,
        "birth_date": p.birth_date.isoformat() if p.birth_date else None,
        "age": p.age_on(date.today()),
        "sex": p.sex,
        "contact": p.contact,
        "clinic_ref": p.clinic_ref,
        "created_at": p.created_at.isoformat(),
    }
    if consents is not None:
        out["consents"] = [
            {
                "type": c.consent_type,
                "version": c.version,
                "granted": c.granted,
                "recorded_at": c.recorded_at.isoformat(),
            }
            for c in consents
        ]
        out["has_care_consent"] = has_care_consent(consents)
    return out


def has_care_consent(consents: list[Consent]) -> bool:
    latest = max(
        (c for c in consents if c.consent_type == CARE_CONSENT), key=lambda c: c.recorded_at, default=None
    )
    return bool(latest and latest.granted)


def get_patient_for(db: Session, user: User, patient_id: str) -> Patient:
    p = db.get(Patient, patient_id)
    if p is None or p.org_id != user.org_id:
        raise not_found("Patient not found")
    return p


@router.post("")
def create_patient(body: PatientIn, user: User = Depends(clinic_user), db: Session = Depends(get_db)) -> dict:
    if body.site_id:
        site = db.get(Site, body.site_id)
        if site is None or site.org_id != user.org_id:
            raise not_found("Site not found")
    p = Patient(org_id=user.org_id, created_by=user.id, **body.model_dump())
    db.add(p)
    db.flush()
    audit(db, user, "create", "patient", p.id)
    db.commit()
    return patient_out(p, [])


@router.get("")
def search_patients(
    query: str = Query("", max_length=100),
    limit: int = Query(50, le=200),
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Patient).where(Patient.org_id == user.org_id)
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(Patient.full_name.ilike(like), Patient.clinic_ref.ilike(like)))
    patients = db.scalars(stmt.order_by(Patient.created_at.desc()).limit(limit)).all()
    audit(db, user, "view", "patient_list", None, {"query": bool(query), "count": len(patients)})
    db.commit()
    return [patient_out(p) for p in patients]


@router.get("/{patient_id}")
def get_patient(patient_id: str, user: User = Depends(clinic_user), db: Session = Depends(get_db)) -> dict:
    p = get_patient_for(db, user, patient_id)
    consents = db.scalars(select(Consent).where(Consent.patient_id == p.id)).all()
    encounters = db.scalars(
        select(Encounter).where(Encounter.patient_id == p.id).order_by(Encounter.created_at.desc())
    ).all()
    audit(db, user, "view", "patient", p.id)
    db.commit()
    return {
        **patient_out(p, list(consents)),
        "encounters": [
            {"id": e.id, "pack_id": e.pack_id, "status": e.status, "created_at": e.created_at.isoformat()}
            for e in encounters
        ],
    }


@router.post("/{patient_id}/consents")
def record_consent(
    patient_id: str, body: ConsentIn, user: User = Depends(clinic_user), db: Session = Depends(get_db)
) -> dict:
    p = get_patient_for(db, user, patient_id)
    c = Consent(
        org_id=user.org_id,
        patient_id=p.id,
        consent_type=body.consent_type,
        version=body.version,
        granted=body.granted,
        recorded_by=user.id,
    )
    db.add(c)
    audit(db, user, "create", "consent", p.id, {"type": body.consent_type, "granted": body.granted})
    db.commit()
    consents = db.scalars(select(Consent).where(Consent.patient_id == p.id)).all()
    return patient_out(p, list(consents))
