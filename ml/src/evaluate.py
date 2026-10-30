"""Evaluation report (PRD 10.5): per-condition sensitivity/specificity, emergency recall, top-3, ECE, confusion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def ece(probs: np.ndarray, labels: np.ndarray, bins: int = 15) -> float:
    conf = probs.max(axis=1)
    correct = probs.argmax(axis=1) == labels
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (conf > lo) & (conf <= hi)
        if mask.any():
            total += mask.mean() * abs(conf[mask].mean() - correct[mask].mean())
    return float(total)


def evaluate(
    probs: np.ndarray,
    labels: np.ndarray,
    condition_ids: list[str],
    emergency_ids: list[str],
    emergency_threshold: float,
) -> dict[str, Any]:
    n, k = probs.shape
    pred = probs.argmax(axis=1)
    top3 = np.argsort(-probs, axis=1)[:, :3]
    confusion = np.zeros((k, k), dtype=int)
    for t, p in zip(labels, pred, strict=True):
        confusion[t, p] += 1

    per_condition = {}
    for i, cid in enumerate(condition_ids):
        pos = labels == i
        tp = int(((pred == i) & pos).sum())
        fn = int(((pred != i) & pos).sum())
        tn = int(((pred != i) & ~pos).sum())
        fp = int(((pred == i) & ~pos).sum())
        row: dict[str, Any] = {
            "n": int(pos.sum()),
            "sensitivity": tp / (tp + fn) if tp + fn else None,
            "specificity": tn / (tn + fp) if tn + fp else None,
            "top3_recall": float((top3[pos] == i).any(axis=1).mean()) if pos.any() else None,
        }
        if cid in emergency_ids:
            row["emergency_recall_at_threshold"] = (
                float((probs[pos, i] >= emergency_threshold).mean()) if pos.any() else None
            )
        per_condition[cid] = row

    return {
        "n": int(n),
        "top1_accuracy": float((pred == labels).mean()) if n else None,
        "top3_accuracy": float((top3 == labels[:, None]).any(axis=1).mean()) if n else None,
        "ece": ece(probs, labels) if n else None,
        "emergency_threshold": emergency_threshold,
        "per_condition": per_condition,
        "confusion_matrix": {"labels": condition_ids, "rows_true_cols_pred": confusion.tolist()},
    }


def write_report(report: dict[str, Any], out_dir: Path, title: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation.json").write_text(json.dumps(report, indent=2))
    lines = [f"# {title}", ""]
    fmt = lambda v: "-" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)  # noqa: E731
    lines.append(
        f"n={report['n']}  top-1={fmt(report['top1_accuracy'])}  top-3={fmt(report['top3_accuracy'])}  "
        f"ECE={fmt(report['ece'])}"
    )
    lines += ["", "| condition | n | sensitivity | specificity | top-3 recall | emergency recall |", "|---|---|---|---|---|---|"]
    for cid, r in report["per_condition"].items():
        lines.append(
            f"| {cid} | {r['n']} | {fmt(r['sensitivity'])} | {fmt(r['specificity'])} | "
            f"{fmt(r['top3_recall'])} | {fmt(r.get('emergency_recall_at_threshold'))} |"
        )
    (out_dir / "evaluation.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
