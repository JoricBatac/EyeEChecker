from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.orgs.models import OrgPack
from app.modules.packs.loader import Pack, get_packs
from app.modules.packs.models import ConditionState


def resolve_condition_states(db: Session, pack: Pack, org_id: str, model_version: str) -> dict[str, str]:
    """Effective AI state per classifiable condition. Most specific row wins:
    org + model version > org > model version > pack-wide > pack default."""
    rows = db.scalars(
        select(ConditionState).where(
            ConditionState.pack_id == pack.id,
            or_(ConditionState.org_id == org_id, ConditionState.org_id.is_(None)),
            or_(ConditionState.model_version == model_version, ConditionState.model_version.is_(None)),
        )
    ).all()
    states: dict[str, str] = {cid: pack.default_condition_state for cid in pack.classifiable_ids}
    best: dict[str, int] = {}
    for r in rows:
        if r.condition_id not in states:
            continue
        rank = (2 if r.org_id else 0) + (1 if r.model_version else 0)
        if rank >= best.get(r.condition_id, -1):
            best[r.condition_id] = rank
            states[r.condition_id] = r.state
    return states


def enabled_pack_ids(db: Session, org_id: str) -> list[str]:
    packs = get_packs()
    rows = db.scalars(select(OrgPack).where(OrgPack.org_id == org_id, OrgPack.enabled.is_(True))).all()
    return [r.pack_id for r in rows if r.pack_id in packs and not packs[r.pack_id].placeholder]
