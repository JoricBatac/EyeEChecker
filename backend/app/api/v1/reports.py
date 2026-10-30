from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import clinic_user, clinician
from app.core.db import get_db
from app.core.errors import not_found
from app.core.storage import Storage, get_storage
from app.modules.audit.service import audit
from app.modules.encounters.models import Encounter
from app.modules.orgs.models import User
from app.modules.reports import service as svc
from app.modules.reports.models import Report

router = APIRouter(prefix="/reports", tags=["reports"])


class ContentIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


def get_report_for(db: Session, user: User, report_id: str) -> Report:
    r = db.get(Report, report_id)
    if r is None or r.org_id != user.org_id:
        raise not_found("Report not found")
    return r


@router.get("/{report_id}")
def get_report(report_id: str, user: User = Depends(clinic_user), db: Session = Depends(get_db)) -> dict:
    r = get_report_for(db, user, report_id)
    audit(db, user, "view", "report", r.id)
    db.commit()
    return svc.report_out(r)


@router.patch("/{report_id}")
def edit_report(
    report_id: str, body: ContentIn, user: User = Depends(clinic_user), db: Session = Depends(get_db)
) -> dict:
    return svc.report_out(svc.edit_report(db, user, get_report_for(db, user, report_id), body.content))


@router.post("/{report_id}/polish")
def polish(report_id: str, user: User = Depends(clinic_user), db: Session = Depends(get_db)) -> dict:
    report, polished = svc.polish_report(db, user, get_report_for(db, user, report_id))
    return {**svc.report_out(report), "polished": polished}


@router.post("/{report_id}/addenda")
def addendum(
    report_id: str, body: ContentIn, user: User = Depends(clinician), db: Session = Depends(get_db)
) -> dict:
    return svc.report_out(svc.add_addendum(db, user, get_report_for(db, user, report_id), body.content))


@router.post("/{report_id}/sign")
def sign(
    report_id: str,
    user: User = Depends(clinician),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    r = get_report_for(db, user, report_id)
    enc = db.get(Encounter, r.encounter_id)
    assert enc
    return svc.sign_off(db, storage, user, enc, [r.id])


@router.get("/{report_id}/pdf")
def pdf(
    report_id: str,
    user: User = Depends(clinic_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    r = get_report_for(db, user, report_id)
    data = svc.report_pdf(db, storage, user, r)
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{r.type}-{r.id[:8]}.pdf"'},
    )
