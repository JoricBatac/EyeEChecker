"""Test 1, step 4: blind review sheet. Shuffles outputs and hides the source.

    python review_sheet.py            -> out/review_sheet.csv (send to reviewers), out/review_key.csv (keep)
    python review_sheet.py --decide out/review_sheet_filled.csv

Reviewers score 1-5: accuracy, clarity, filipino (blank for English outputs), edits (5 = none needed).
Decision rule (agreed beforehand, PRD 10.7): move to 27B if 4B has any invented medical fact,
averages < 4 on Filipino naturalness, or needs significant edits (edits <= 2) on more than 30% of reports.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from statistics import mean

HERE = Path(__file__).parent
OUT = HERE / "out"
SCORES = ["accuracy", "clarity", "filipino", "edits"]


def make_sheet(seed: int) -> None:
    rows = [json.loads(line) for line in (OUT / "outputs.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if not r["output"].startswith("__ERROR__")]
    random.Random(seed).shuffle(rows)
    with open(OUT / "review_sheet.csv", "w", newline="", encoding="utf-8") as f, open(
        OUT / "review_key.csv", "w", newline="", encoding="utf-8"
    ) as k:
        sheet, key = csv.writer(f), csv.writer(k)
        sheet.writerow(["item", "case", "output", *SCORES, "comments"])
        key.writerow(["item", "case", "source"])
        for i, r in enumerate(rows, start=1):
            sheet.writerow([i, r["case"], r["output"], "", "", "", "", ""])
            key.writerow([i, r["case"], r["source"]])
    print(f"wrote {len(rows)} items to {OUT / 'review_sheet.csv'} (key in review_key.csv)")


def decide(filled: Path) -> None:
    key = {row["item"]: row["source"] for row in csv.DictReader(open(OUT / "review_key.csv", encoding="utf-8"))}
    facts = [json.loads(line) for line in (OUT / "fact_check.jsonl").read_text(encoding="utf-8").splitlines()]
    by_source: dict[str, list[dict]] = {}
    for row in csv.DictReader(open(filled, encoding="utf-8")):
        by_source.setdefault(key[row["item"]], []).append(row)

    for source, rows in sorted(by_source.items()):
        avg = {s: mean(float(r[s]) for r in rows if r[s]) if any(r[s] for r in rows) else None for s in SCORES}
        print(source, {k: round(v, 2) if v else None for k, v in avg.items()})

    four = by_source.get("4b", [])
    invented = [f for f in facts if f["source"] == "4b" and not f["pass"]]
    fil = [float(r["filipino"]) for r in four if r["filipino"]]
    heavy_edits = sum(1 for r in four if r["edits"] and float(r["edits"]) <= 2) / max(len(four), 1)
    reasons = []
    if invented:
        reasons.append(f"{len(invented)} 4B outputs with invented medical facts")
    if fil and mean(fil) < 4:
        reasons.append(f"Filipino naturalness {mean(fil):.2f} < 4")
    if heavy_edits > 0.30:
        reasons.append(f"significant edits on {heavy_edits:.0%} of 4B reports")
    print("\nDECISION:", "move to 27B (" + "; ".join(reasons) + ")" if reasons else "stay on 4B")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decide", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    decide(args.decide) if args.decide else make_sheet(args.seed)


if __name__ == "__main__":
    main()
