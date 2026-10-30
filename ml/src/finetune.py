"""Stage C: fine-tune the best backbone end to end (needs ~500+ photos per condition and a GPU).

    python -m src.finetune --config configs/eye.yaml --backbone efficientnet --export
"""

from __future__ import annotations

import argparse

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

from src.backbones import Classifier, build_encoder
from src.calibrate import fit_temperature
from src.common import load_config, load_pack_conditions, new_run_dir, resolve
from src.dataset import ImageDataset, dataset_hash, load_manifest, split_by_subject
from src.evaluate import evaluate, write_report
from src.export_onnx import export


@torch.no_grad()
def logits_for(model: Classifier, loader: DataLoader, device: str) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    out, labels = [], []
    for x, y in loader:
        out.append(model(x.to(device)).cpu().numpy())
        labels.append(y.numpy())
    return np.concatenate(out), np.concatenate(labels)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--backbone", required=True)
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    pack = load_pack_conditions(cfg["pack_dir"])
    ids = pack["ids"]
    rows = load_manifest(cfg["manifest"], cfg["image_root"], ids)
    frozen: set[str] = set()
    if cfg.get("frozen_test_manifest") and resolve(cfg["frozen_test_manifest"]).exists():
        frozen = {r["subject_hash"] for r in load_manifest(cfg["frozen_test_manifest"], cfg["image_root"], ids)}
    s = cfg["split"]
    splits = split_by_subject(rows, s["val_fraction"], s["test_fraction"], s["seed"], s.get("holdout_site"), frozen)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    ft = cfg["finetune"]
    encoder = build_encoder(args.backbone, cfg["backbones"][args.backbone])
    model = Classifier(encoder, len(ids)).to(device)
    mk = lambda split, aug: ImageDataset(  # noqa: E731
        splits[split], ids, encoder.input_size, encoder.mean, encoder.std, cfg["augment"] if aug else None
    )
    train_dl = DataLoader(mk("train", True), batch_size=ft["batch_size"], shuffle=True)
    val_dl = DataLoader(mk("val", False), batch_size=ft["batch_size"])
    test_dl = DataLoader(mk("test", False), batch_size=ft["batch_size"])

    opt = torch.optim.AdamW(
        [
            {"params": model.encoder.parameters(), "lr": ft["lr_backbone"]},
            {"params": model.head.parameters(), "lr": ft["lr_head"]},
        ],
        weight_decay=ft["weight_decay"],
    )
    loss_fn = nn.CrossEntropyLoss()
    best, best_state = float("inf"), None
    for epoch in range(ft["epochs"]):
        model.train()
        for x, y in train_dl:
            opt.zero_grad()
            loss_fn(model(x.to(device)), y.to(device)).backward()
            opt.step()
        vl, vy = logits_for(model, val_dl, device)
        val_loss = nn.functional.cross_entropy(torch.tensor(vl), torch.tensor(vy)).item()
        print(f"epoch {epoch + 1}: val loss {val_loss:.4f}")
        if val_loss < best:
            best, best_state = val_loss, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    if best_state:
        model.load_state_dict(best_state)

    vl, vy = logits_for(model, val_dl, device)
    temperature = fit_temperature(vl, vy)
    tl, ty = logits_for(model, test_dl, device)
    probs = torch.softmax(torch.tensor(tl) / temperature, dim=1).numpy()
    report = evaluate(probs, ty, ids, pack["emergency"], cfg["emergency_threshold"])
    report["temperature"] = temperature

    run = new_run_dir(f"finetune-{cfg['pack_id']}-{args.backbone}")
    torch.save(model.state_dict(), run / "model.pt")
    write_report(report, run, f"Fine-tune: {cfg['pack_id']} / {args.backbone}")
    if args.export:
        export(
            model.cpu(),
            run / "onnx",
            pack_id=cfg["pack_id"],
            model_version=f"{cfg['pack_id']}-ft-{args.backbone}-{run.name[:15]}",
            condition_ids=ids,
            temperature=temperature,
            thresholds={"emergency": cfg["emergency_threshold"]},
            data_hash=dataset_hash(rows),
        )


if __name__ == "__main__":
    main()
