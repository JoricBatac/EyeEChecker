"""Stage B: frozen encoder + trained linear layer (PRD 10.2).

    python -m src.train_probe --config configs/eye.yaml --backbone medsiglip --export
    python -m src.train_probe --config configs/eye.yaml --backbone efficientnet

Run both backbones on the same split and keep the winner.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np
import torch
from torch import nn

from src.backbones import Classifier, Encoder, build_encoder
from src.calibrate import fit_temperature
from src.common import load_config, load_pack_conditions, new_run_dir, resolve
from src.dataset import dataset_hash, load_manifest, split_by_subject
from src.embed_cache import embed_rows
from src.evaluate import evaluate, write_report
from src.export_onnx import export


def embed(encoder: Encoder, rows: list[dict[str, Any]], ids: list[str], batch_size: int = 16) -> tuple[np.ndarray, np.ndarray]:
    labels = np.array([ids.index(r["label"]) for r in rows], dtype=np.int64)
    return embed_rows(encoder, rows, batch_size), labels


def train_head(
    train: tuple[np.ndarray, np.ndarray], val: tuple[np.ndarray, np.ndarray], num_classes: int, cfg: dict[str, Any]
) -> nn.Linear:
    torch.manual_seed(0)
    xt, yt = torch.tensor(train[0]), torch.tensor(train[1])
    xv, yv = torch.tensor(val[0]), torch.tensor(val[1])
    counts = torch.bincount(yt, minlength=num_classes).float().clamp(min=1)
    loss_fn = nn.CrossEntropyLoss(weight=counts.sum() / (num_classes * counts))
    head = nn.Linear(xt.shape[1], num_classes)
    opt = torch.optim.AdamW(head.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    best, best_state, stale = float("inf"), None, 0
    for _ in range(cfg["epochs"]):
        head.train()
        opt.zero_grad()
        loss_fn(head(xt), yt).backward()
        opt.step()
        head.eval()
        with torch.no_grad():
            v = nn.functional.cross_entropy(head(xv), yv).item() if len(yv) else 0.0
        if v < best - 1e-4:
            best, best_state, stale = v, {k: t.clone() for k, t in head.state_dict().items()}, 0
        else:
            stale += 1
            if stale >= cfg["patience"]:
                break
    if best_state:
        head.load_state_dict(best_state)
    return head


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--backbone", required=True)
    ap.add_argument("--export", action="store_true", help="export ONNX + metadata.json for the backend")
    ap.add_argument("--model-version", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    pack = load_pack_conditions(cfg["pack_dir"], cfg.get("conditions"), cfg.get("condition_groups"))
    if args.export and pack["research_subset"]:
        ap.error("this config trains a research subset of the pack's conditions; it cannot be exported")
    ids = pack["ids"]
    rows = load_manifest(cfg["manifest"], cfg["image_root"], ids)
    frozen_subjects: set[str] = set()
    if cfg.get("frozen_test_manifest") and resolve(cfg["frozen_test_manifest"]).exists():
        frozen = load_manifest(cfg["frozen_test_manifest"], cfg["image_root"], ids)
        frozen_subjects = {r["subject_hash"] for r in frozen}
    s = cfg["split"]
    splits = split_by_subject(
        rows, s["val_fraction"], s["test_fraction"], s["seed"], s.get("holdout_site"), frozen_subjects
    )
    print({k: len(v) for k, v in splits.items()}, f"(excluded {len(frozen_subjects)} frozen-test subjects)")

    encoder = build_encoder(args.backbone, cfg["backbones"][args.backbone]).eval()
    for p in encoder.parameters():
        p.requires_grad_(False)
    emb = {k: embed(encoder, v, ids) for k, v in splits.items()}
    head = train_head(emb["train"], emb["val"], len(ids), cfg["probe"])

    with torch.no_grad():
        val_logits = head(torch.tensor(emb["val"][0])).numpy()
        test_logits = head(torch.tensor(emb["test"][0])).numpy()
    temperature = fit_temperature(val_logits, emb["val"][1]) if len(val_logits) else 1.0
    probs = torch.softmax(torch.tensor(test_logits) / temperature, dim=1).numpy()
    report = evaluate(probs, emb["test"][1], ids, pack["emergency"], cfg["emergency_threshold"])
    report["temperature"] = temperature
    report["splits"] = {k: len(v) for k, v in splits.items()}

    run = new_run_dir(f"probe-{cfg['pack_id']}-{args.backbone}")
    torch.save(head.state_dict(), run / "head.pt")
    (run / "config.json").write_text(json.dumps({k: v for k, v in cfg.items()}, indent=2, default=str))
    write_report(report, run, f"Linear probe: {cfg['pack_id']} / {args.backbone}")

    if args.export:
        version = args.model_version or f"{cfg['pack_id']}-probe-{args.backbone}-{run.name[:15]}"
        export(
            Classifier(encoder, len(ids), head),
            run / "onnx",
            pack_id=cfg["pack_id"],
            model_version=version,
            condition_ids=ids,
            temperature=temperature,
            thresholds={"emergency": cfg["emergency_threshold"]},
            data_hash=dataset_hash(rows),
        )
    print(f"run saved to {run}")


if __name__ == "__main__":
    main()
