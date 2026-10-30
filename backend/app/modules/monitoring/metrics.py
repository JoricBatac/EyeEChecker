"""AI vs clinician agreement (FR-37). Measured on pre-reveal assessments so the AI can't have influenced them."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessment.models import Assessment
from app.modules.encounters.models import AIResult, Encounter, Feedback
from app.modules.packs.loader import get_pack


@dataclass
class Case:
    encounter: Encounter
    ai: AIResult
    pre: Assessment
    post: Assessment | None

    @property
    def label(self) -> str:
        return self.pre.diagnoses[0]["condition_id"]

    @property
    def ranked(self) -> list[str]:
        return [c for c, _ in sorted(self.ai.probabilities.items(), key=lambda x: x[1], reverse=True)]

    @property
    def top3_agrees(self) -> bool:
        return self.label in self.ranked[:3]


def load_cases(db: Session, pack_id: str | None = None) -> list[Case]:
    stmt = select(Encounter).where(Encounter.status != "expired")
    if pack_id:
        stmt = stmt.where(Encounter.pack_id == pack_id)
    cases = []
    for enc in db.scalars(stmt).all():
        ai = db.scalars(
            select(AIResult)
            .where(AIResult.encounter_id == enc.id)
            .order_by(AIResult.created_at.desc())
            .limit(1)
        ).first()
        phases = {
            a.phase: a for a in db.scalars(select(Assessment).where(Assessment.encounter_id == enc.id)).all()
        }
        if ai and "pre_reveal" in phases and ai.probabilities:
            cases.append(Case(enc, ai, phases["pre_reveal"], phases.get("post_reveal")))
    return cases


def _ece(cases: list[Case], bins: int = 10) -> float | None:
    if not cases:
        return None
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for c in cases:
        top = c.ranked[0]
        conf = c.ai.probabilities[top]
        buckets[min(int(conf * bins), bins - 1)].append((conf, top == c.label))
    total = len(cases)
    return round(
        sum(
            len(b) / total * abs(sum(x for x, _ in b) / len(b) - sum(y for _, y in b) / len(b))
            for b in buckets.values()
        ),
        4,
    )


def compute_metrics(db: Session, pack_id: str) -> dict:
    pack = get_pack(pack_id)
    if pack is None or pack.ruleset is None:
        return {}
    threshold = pack.ruleset.emergency_model_threshold
    cases = load_cases(db, pack_id)
    by_version: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_version[c.ai.model_version].append(c)

    versions = []
    for version, vcases in by_version.items():
        per_condition = []
        for cond in pack.conditions:
            cc = [c for c in vcases if c.label == cond.id]
            if not cc:
                continue
            states: dict[str, int] = defaultdict(int)
            for c in cc:
                states[c.ai.condition_states.get(cond.id, "off")] += 1
            row = {
                "condition_id": cond.id,
                "n": len(cc),
                "top1_agreement": round(sum(c.ranked[0] == cond.id for c in cc) / len(cc), 3),
                "top3_agreement": round(sum(c.top3_agrees for c in cc) / len(cc), 3),
                "states": dict(states),
            }
            if cond.emergency:
                row["emergency_sensitivity"] = round(
                    sum(c.ai.probabilities.get(cond.id, 0) >= threshold for c in cc) / len(cc), 3
                )
            per_condition.append(row)
        revealed = [c for c in vcases if c.ai.revealed_at is not None]
        versions.append(
            {
                "model_version": version,
                "cases": len(vcases),
                "top3_agreement": round(sum(c.top3_agrees for c in vcases) / len(vcases), 3),
                "ece": _ece(vcases),
                "changed_after_reveal_rate": round(
                    sum(bool(c.post and c.post.changed_after_reveal) for c in revealed) / len(revealed), 3
                )
                if revealed
                else None,
                "per_condition": per_condition,
            }
        )

    feedback: dict[str, int] = defaultdict(int)
    for f in db.scalars(select(Feedback)).all():
        feedback[f.rating] += 1
    return {
        "pack_id": pack_id,
        "visible_criteria": {"top3_agreement": 0.8, "emergency_sensitivity": 0.95, "ece": 0.05},
        "versions": versions,
        "feedback": dict(feedback),
    }
