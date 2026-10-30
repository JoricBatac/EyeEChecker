"""Group near-duplicate photos (crops, resizes, re-encodes of one picture) under one subject.

    python -m src.near_duplicates --config <cfg>                     # report only
    python -m src.near_duplicates --config <cfg> --threshold 0.95 --apply

Datasets without patient IDs often hold the same picture several times. If copies land in both the
training and test splits, test scores are inflated. This compares frozen-encoder embeddings (cached,
see src/embed_cache.py), which survive cropping and resizing where byte hashes do not. With --apply,
each group of near-duplicates gets one subject_hash in the manifest, so split_by_subject keeps them
together. Pairs whose labels disagree are flagged for label review, never resolved automatically.
"""

from __future__ import annotations

import argparse
import csv

import numpy as np

from src.backbones import build_encoder
from src.common import load_config, load_pack_conditions, resolve
from src.dataset import load_manifest
from src.embed_cache import embed_rows

REPORT_THRESHOLDS = (0.90, 0.92, 0.94, 0.95, 0.96, 0.98)


def find_groups(feats: np.ndarray, threshold: float) -> tuple[list[int], list[tuple[int, int, float]]]:
    """Union-find over pairs with cosine similarity >= threshold. Returns each row's group root and the pairs."""
    f = feats / np.linalg.norm(feats, axis=1, keepdims=True)
    sim = f @ f.T
    i_idx, j_idx = np.where(np.triu(sim, k=1) >= threshold)
    parent = list(range(len(f)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(i_idx, j_idx, strict=True):
        parent[root(int(i))] = root(int(j))
    pairs = [(int(i), int(j), float(sim[i, j])) for i, j in zip(i_idx, j_idx, strict=True)]
    return [root(i) for i in range(len(f))], pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--backbone", default="medsiglip")
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--apply", action="store_true", help="rewrite subject_hash in the manifest")
    args = ap.parse_args()

    cfg = load_config(args.config)
    pack = load_pack_conditions(cfg["pack_dir"], cfg.get("conditions"), cfg.get("condition_groups"))
    rows = load_manifest(cfg["manifest"], cfg["image_root"], pack["ids"])
    encoder = build_encoder(args.backbone, cfg["backbones"][args.backbone]).eval()
    feats = embed_rows(encoder, rows)

    f = feats / np.linalg.norm(feats, axis=1, keepdims=True)
    upper = (f @ f.T)[np.triu_indices(len(f), k=1)]
    print("pairs at or above each cosine similarity:")
    for t in REPORT_THRESHOLDS:
        print(f"  {t:.2f}: {int((upper >= t).sum())}")

    groups, pairs = find_groups(feats, args.threshold)
    manifest = resolve(cfg["manifest"])
    report = manifest.with_name("near_duplicates.csv")
    with open(report, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["similarity", "label_conflict", "image_a", "label_a", "image_b", "label_b"])
        for i, j, s in sorted(pairs, key=lambda p: -p[2]):
            a, b = rows[i], rows[j]
            w.writerow([f"{s:.4f}", a["label"] != b["label"], a["image_id"], a["label"], b["image_id"], b["label"]])
    members: dict[int, list[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    multi = [m for m in members.values() if len(m) > 1]
    conflicts = sum(rows[i]["label"] != rows[j]["label"] for i, j, _ in pairs)
    print(
        f"threshold {args.threshold}: {len(pairs)} pairs in {len(multi)} groups covering "
        f"{sum(len(m) for m in multi)} photos; {conflicts} pairs have different labels. Report: {report}"
    )

    if not args.apply:
        print("report only; rerun with --apply to group them in the manifest")
        return
    largest = max((len(m) for m in multi), default=0)
    if largest > max(10, len(rows) // 50):
        raise SystemExit(
            f"refusing to apply: one group holds {largest} photos, which means the threshold is too low "
            "for this encoder, not that they are copies. Raise --threshold and check the report."
        )
    subject = {rows[i]["image_id"]: min(rows[k]["subject_hash"] for k in members[groups[i]]) for i in range(len(rows))}
    with open(manifest, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames, out_rows = reader.fieldnames, list(reader)
    for r in out_rows:
        r["subject_hash"] = subject.get(r["image_id"], r["subject_hash"])
    with open(manifest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"updated subject_hash for {sum(len(m) for m in multi)} photos in {manifest}")


if __name__ == "__main__":
    main()
