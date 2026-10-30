"""Per-condition agreement between MedSigLIP and clinicians' own (pre-AI) picks, from anonymous score logs.

    python -m scripts.assist_metrics [--pack eye]

Targets before a condition's suggestions may be trusted (PRD 10.3): top-3 agreement >= 80%,
emergency sensitivity >= 95%.
"""

import argparse
from collections import defaultdict

from sqlalchemy import select

from app import models  # noqa: F401
from app.core.db import SessionLocal
from app.modules.assist.models import AssistScore
from app.modules.packs.loader import get_pack


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="eye")
    args = ap.parse_args()
    pack = get_pack(args.pack)
    assert pack and pack.ruleset
    threshold = pack.ruleset.emergency_model_threshold
    with SessionLocal() as db:
        rows = db.scalars(select(AssistScore).where(AssistScore.pack_id == args.pack)).all()
    by_version: dict[str, list[AssistScore]] = defaultdict(list)
    for r in rows:
        by_version[r.model_version].append(r)
    if not rows:
        print("No scores yet.")
    for version, scores in by_version.items():
        print(f"\nModel {version}: {len(scores)} cases")
        print(f"{'condition':26} {'n':>4} {'top1':>6} {'top3':>6} {'emerg.sens':>10}")
        for c in pack.conditions:
            cases = [s for s in scores if s.clinician_dx and s.clinician_dx[0] == c.id]
            if not cases:
                continue
            ranked = [sorted(s.probabilities, key=s.probabilities.get, reverse=True) for s in cases]
            top1 = sum(r[0] == c.id for r in ranked) / len(cases)
            top3 = sum(c.id in r[:3] for r in ranked) / len(cases)
            sens = (
                f"{sum(s.probabilities.get(c.id, 0) >= threshold for s in cases) / len(cases):10.0%}"
                if c.emergency
                else f"{'-':>10}"
            )
            print(f"{c.id:26} {len(cases):4} {top1:6.0%} {top3:6.0%} {sens}")
        changed = [s for s in scores if s.changed_after_reveal is not None]
        if changed:
            print(
                f"Changed mind after seeing AI: {sum(s.changed_after_reveal for s in changed) / len(changed):.0%}"
            )
        ratings: dict[str, int] = defaultdict(int)
        for s in scores:
            if s.rating:
                ratings[s.rating] += 1
        if ratings:
            print("Ratings:", dict(ratings))


if __name__ == "__main__":
    main()
