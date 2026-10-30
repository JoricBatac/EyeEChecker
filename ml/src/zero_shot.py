"""Stage A / Test 2: MedSigLIP zero-shot against the pack's condition prompts.

    python -m src.zero_shot --config configs/eye.yaml                 # frozen test set (Test 2 baseline)
    python -m src.zero_shot --config configs/eye.yaml --manifest data/eye/manifest.csv

Runs on your own machine or VM. Never upload patient photos to free notebook services.
Uses the same prompts and scoring as the backend's ZeroShotClassifier.
"""

from __future__ import annotations

import argparse
import csv
import os

import numpy as np
import torch
from PIL import Image

from src.backbones import as_tensor
from src.common import load_config, load_pack_conditions, new_run_dir, hf_token
from src.dataset import load_manifest
from src.evaluate import evaluate, write_report


class MedSigLIPZeroShot:
    def __init__(self, model_id: str, prompts: dict[str, list[str]]):
        from transformers import AutoModel, AutoProcessor

        token = hf_token()
        self.model = AutoModel.from_pretrained(model_id, token=token).eval()
        self.processor = AutoProcessor.from_pretrained(model_id, token=token)
        self.ids = list(prompts)
        with torch.no_grad():
            embs = []
            for cid in self.ids:
                tok = self.processor(text=prompts[cid], padding="max_length", return_tensors="pt")
                e = as_tensor(self.model.get_text_features(**tok))
                e = (e / e.norm(dim=-1, keepdim=True)).mean(0)
                embs.append(e / e.norm())
            self.text = torch.stack(embs)

    @torch.no_grad()
    def predict(self, images: list[Image.Image]) -> np.ndarray:
        inputs = self.processor(images=images, return_tensors="pt")
        img = as_tensor(self.model.get_image_features(**inputs))
        img = img / img.norm(dim=-1, keepdim=True)
        logits = img @ self.text.T * self.model.logit_scale.exp() + self.model.logit_bias
        return torch.softmax(logits, dim=-1).numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--manifest", default=None, help="defaults to the frozen test manifest")
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()

    cfg = load_config(args.config)
    pack = load_pack_conditions(cfg["pack_dir"], cfg.get("conditions"), cfg.get("condition_groups"))
    manifest = args.manifest or cfg["frozen_test_manifest"]
    rows = load_manifest(manifest, cfg["image_root"], pack["ids"])
    model = MedSigLIPZeroShot(cfg["backbones"]["medsiglip"]["model_id"], pack["prompts"])

    probs = []
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i : i + args.batch_size]
        images = []
        for r in batch:
            with Image.open(r["path"]) as im:
                images.append(im.convert("RGB"))
        probs.append(model.predict(images))
        print(f"{min(i + args.batch_size, len(rows))}/{len(rows)}", end="\r")
    p = np.concatenate(probs)
    labels = np.array([pack["ids"].index(r["label"]) for r in rows])

    run = new_run_dir(f"zeroshot-{cfg['pack_id']}")
    with open(run / "probabilities.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "label", *pack["ids"]])
        for r, row in zip(rows, p, strict=True):
            w.writerow([r["image_id"], r["label"], *[f"{x:.4f}" for x in row]])
    report = evaluate(p, labels, pack["ids"], pack["emergency"], cfg["emergency_threshold"])
    write_report(report, run, f"Zero-shot MedSigLIP baseline: {cfg['pack_id']}")
    print(f"run saved to {run}")


if __name__ == "__main__":
    main()
