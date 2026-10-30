"""Test 1, step 5: flag any condition, medication or dose in an output that is not in its input.

    python fact_check.py --cases cases.jsonl

Any invented medical fact is a failure. Reads out/outputs.jsonl, writes out/fact_check.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
PACK = HERE.parents[1] / "packs" / "eye"
DOSE = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|mL|%|drops?|gtts?|patak|beses|times)\b", re.IGNORECASE)


def condition_vocab() -> dict[str, set[str]]:
    data = json.loads((PACK / "conditions.json").read_text(encoding="utf-8"))
    vocab = {}
    for c in data["conditions"]:
        names = {c["id"].replace("_", " ")}
        for name in c["name"].values():
            names |= {n.strip().lower() for n in re.split(r"[/()]", name) if len(n.strip()) > 4}
        vocab[c["id"]] = names
    return vocab


def medication_vocab() -> set[str]:
    path = HERE / "medications.txt"
    return {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def check(case: dict, output: str, conditions: dict[str, set[str]], meds: set[str]) -> list[str]:
    text = output.lower()
    source = json.dumps(case, ensure_ascii=False).lower()
    allowed = {c["id"] for c in case["conditions"]}
    problems = []
    for cid, names in conditions.items():
        if cid in allowed or cid in ("normal", "other_unclear"):
            continue
        hit = next((n for n in names if n in text and n not in source), None)
        if hit:
            problems.append(f"invented condition: {hit}")
    problems += [f"invented medication: {m}" for m in meds if re.search(rf"\b{re.escape(m)}\b", text) and m not in source]
    for m in DOSE.finditer(output):
        if m.group(0).lower() not in source:
            problems.append(f"dose or frequency not in input: {m.group(0)}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(HERE / "cases.example.jsonl"))
    args = ap.parse_args()
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    conditions, meds = condition_vocab(), medication_vocab()
    results = []
    for line in (HERE / "out" / "outputs.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        problems = check(cases[row["case"]], row["output"], conditions, meds)
        results.append({**row, "problems": problems, "pass": not problems})
    with open(HERE / "out" / "fact_check.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
    for source in sorted({r["source"] for r in results}):
        rows = [r for r in results if r["source"] == source]
        failed = [r for r in rows if not r["pass"]]
        print(f"{source:10} {len(rows) - len(failed)}/{len(rows)} pass")
        for r in failed:
            print(f"   case {r['case']}: {'; '.join(r['problems'])}")


if __name__ == "__main__":
    main()
