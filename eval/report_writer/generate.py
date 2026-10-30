"""Test 1, step 3: generate report outputs from the template baseline and each MedGemma endpoint.

    python generate.py --cases cases.jsonl \
        --endpoint 4b=http://localhost:8001 --endpoint 27b=http://localhost:8002

Endpoints are OpenAI-compatible (vLLM). Payloads are de-identified, so free notebook GPUs are acceptable here.
Output: out/outputs.jsonl (one line per case x source).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

HERE = Path(__file__).parent
SYSTEM_PROMPT = (HERE.parents[1] / "backend/app/modules/llm/system_prompt.txt").read_text(encoding="utf-8").strip()
MODEL_IDS = {"4b": "google/medgemma-4b-it", "27b": "google/medgemma-27b-text-it"}


def template_baseline(case: dict) -> str:
    """Plain structured rendering, standing in for the deterministic template."""
    lines = [f"# {case['report_type'].replace('_', ' ').title()}", "", "{{PATIENT_NAME}} | {{DATE}}", ""]
    lines += [f"- {c['name']}" + (f" ({c['side']})" if c.get("side") else "") for c in case["conditions"]]
    lines += ["", f"Urgency: {case['urgency']}", ""]
    lines += [f"- {f['label']}: {f['value']}" for f in case["findings"]]
    lines += [""] + [f"- {p}" for p in case["plan"]]
    lines += [f"- {r}" for r in case["referral_reasons"]]
    return "\n".join(lines)


def call(base_url: str, model: str, case: dict, timeout: float) -> str:
    r = httpx.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json={
            "model": model,
            "temperature": 0.2,
            "max_tokens": 1200,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(case)}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(HERE / "cases.example.jsonl"))
    ap.add_argument("--endpoint", action="append", default=[], help="name=base_url, e.g. 4b=http://host:8000")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()

    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    out_dir = HERE / "out"
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / "outputs.jsonl", "w", encoding="utf-8") as f:
        for i, case in enumerate(cases):
            f.write(json.dumps({"case": i, "source": "template", "output": template_baseline(case)}) + "\n")
            for spec in args.endpoint:
                name, url = spec.split("=", 1)
                try:
                    text = call(url, MODEL_IDS.get(name, name), case, args.timeout)
                except Exception as exc:
                    text = f"__ERROR__ {exc}"
                f.write(json.dumps({"case": i, "source": name, "output": text}) + "\n")
            print(f"case {i + 1}/{len(cases)} done")
    print(f"wrote {out_dir / 'outputs.jsonl'}")


if __name__ == "__main__":
    main()
