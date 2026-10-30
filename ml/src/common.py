from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

ML_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_absolute():
        path = ML_ROOT / path
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["_path"] = str(path)
    return cfg


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ML_ROOT / p).resolve()


def load_pack_conditions(
    pack_dir: str | Path,
    only: list[str] | None = None,
    groups: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Condition IDs, prompts and emergency flags from the pack, so labels always match production.

    Research configs can train on a subset (`only`) and merge pack conditions a dataset does not separate
    (`groups`, e.g. conjunctivitis -> viral/bacterial/allergic). Such models must not be exported to a pack.
    """
    data = json.loads((resolve(pack_dir) / "conditions.json").read_text(encoding="utf-8"))
    conditions = {c["id"]: c for c in data["conditions"] if c.get("classifiable", True)}
    groups = groups or {}
    ids = only or list(conditions)
    prompts, emergency = {}, []
    for cid in ids:
        members = groups.get(cid, [cid])
        unknown = [m for m in members if m not in conditions]
        if unknown:
            raise ValueError(f"condition {cid}: unknown pack conditions {unknown}")
        prompts[cid] = [p for m in members for p in conditions[m].get("zero_shot_prompts", [])]
        if any(conditions[m].get("emergency") for m in members):
            emergency.append(cid)
    return {"ids": ids, "prompts": prompts, "emergency": emergency, "research_subset": bool(only or groups)}


def new_run_dir(name: str) -> Path:
    run = ML_ROOT / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
    run.mkdir(parents=True, exist_ok=True)
    return run


TOKEN_NAMES = ("HF_TOKEN", "HUGGINGFFACE_ACCESSTOKEN", "HUGGINGFACE_ACCESSTOKEN")


def hf_token() -> str | None:
    """Hugging Face token from the environment, falling back to the repo-root .env (git-ignored)."""
    for name in TOKEN_NAMES:
        if os.environ.get(name):
            return os.environ[name]
    env = ML_ROOT.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() in TOKEN_NAMES and value.strip():
                return value.split(" #")[0].strip().strip('"').strip("'")
    return None
