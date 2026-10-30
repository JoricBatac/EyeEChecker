from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import clinic_user
from app.core.db import get_db
from app.modules.orgs.models import User
from app.modules.packs.loader import Pack, get_pack
from app.modules.packs.states import enabled_pack_ids

router = APIRouter(prefix="/packs", tags=["packs"])


def pack_out(pack: Pack, profession: str | None) -> dict:
    """Client-facing pack config. Ruleset internals and model details stay on the server."""
    assert pack.exam_form and pack.capture_protocol
    return {
        "id": pack.id,
        "version": pack.version,
        "name": pack.name,
        "pediatric_age_threshold": pack.pediatric_age_threshold,
        "conditions": [
            {
                "id": c.id,
                "name": c.name,
                "default_urgency": c.default_urgency,
                "emergency": c.emergency,
                "always_refer": c.always_refer,
                "required_exam_fields_by_side": c.required_exam_fields_by_side,
            }
            for c in pack.conditions
        ],
        "capture_protocol": pack.capture_protocol.model_dump(),
        "exam_form": pack.exam_form.model_dump(),
        "management": {
            cid: [o.model_dump() for o in opts] for cid, opts in pack.management_for(profession).items()
        },
        "content": pack.content,
        "report_types": sorted({key.split(".")[0] for key in pack.templates}),
        "report_locales": sorted({key.split(".")[1] for key in pack.templates}),
    }


@router.get("")
def list_packs(user: User = Depends(clinic_user), db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for pack_id in enabled_pack_ids(db, user.org_id):
        pack = get_pack(pack_id)
        if pack:
            out.append(pack_out(pack, user.profession))
    return out
