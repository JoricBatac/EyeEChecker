"""Manifest loading, patient-level splits and the image dataset.

Training data comes only from externally supplied datasets (PRD 10.6). Images must live under ml/data/
or under the directory named by ML_EXTERNAL_DATA_ROOT; any other location is refused.
"""

from __future__ import annotations

import csv
import hashlib
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageEnhance
from scanassist_core.preprocess import to_model_input
from torch.utils.data import Dataset

from src.common import ML_ROOT, resolve

MANIFEST_COLUMNS = [
    "image_id", "subject_hash", "view", "label", "label_source", "source_dataset",
    "site", "device_model", "capture", "consent_ref",
]  # fmt: skip


def allowed_roots() -> list[Path]:
    roots = [(ML_ROOT / "data").resolve()]
    if os.environ.get("ML_EXTERNAL_DATA_ROOT"):
        roots.append(Path(os.environ["ML_EXTERNAL_DATA_ROOT"]).resolve())
    return roots


def check_image_root(image_root: Path) -> Path:
    root = image_root.resolve()
    if not any(root == r or r in root.parents for r in allowed_roots()):
        raise ValueError(
            f"image_root {root} is outside the allowed training data locations {allowed_roots()}. "
            "Training data must come from the training data workstream, never from app storage."
        )
    return root


def load_manifest(path: str | Path, image_root: str | Path, condition_ids: list[str]) -> list[dict[str, Any]]:
    root = check_image_root(resolve(image_root))
    rows = []
    with open(resolve(path), newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(MANIFEST_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"manifest missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, start=2):
            if row["label"] not in condition_ids:
                raise ValueError(f"line {i}: label {row['label']!r} is not a classifiable pack condition")
            if not row["consent_ref"]:
                raise ValueError(f"line {i}: consent_ref is required")
            image = (root / row["image_id"]).resolve()
            if root not in image.parents:
                raise ValueError(f"line {i}: image path escapes image_root")
            row["path"] = image
            rows.append(row)
    return rows


def dataset_hash(rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: r["image_id"]):
        h.update(f"{r['image_id']}|{r['label']}|{r['subject_hash']}".encode())
    return h.hexdigest()[:16]


def split_by_subject(
    rows: list[dict[str, Any]],
    val_fraction: float,
    test_fraction: float,
    seed: int,
    holdout_site: str | None = None,
    exclude_subjects: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Every photo of a patient lands in the same split. Optionally hold out one site as the test set."""
    exclude = exclude_subjects or set()
    rows = [r for r in rows if r["subject_hash"] not in exclude]
    if holdout_site:
        test = [r for r in rows if r["site"] == holdout_site]
        rows = [r for r in rows if r["site"] != holdout_site]
        test_fraction = 0.0
    else:
        test = []
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_subject[r["subject_hash"]].append(r)
    subjects = sorted(by_subject)
    random.Random(seed).shuffle(subjects)
    n = len(subjects)
    n_test = round(n * test_fraction)
    n_val = round(n * val_fraction)
    pick = lambda ss: [r for s in ss for r in by_subject[s]]  # noqa: E731
    return {
        "test": test + pick(subjects[:n_test]),
        "val": pick(subjects[n_test : n_test + n_val]),
        "train": pick(subjects[n_test + n_val :]),
    }


class ImageDataset(Dataset):
    def __init__(
        self,
        rows: list[dict[str, Any]],
        condition_ids: list[str],
        input_size: int,
        mean: list[float],
        std: list[float],
        augment: dict[str, Any] | None = None,
    ):
        self.rows = rows
        self.index = {c: i for i, c in enumerate(condition_ids)}
        self.input_size, self.mean, self.std = input_size, mean, std
        self.augment = augment

    def __len__(self) -> int:
        return len(self.rows)

    def _augment(self, img: Image.Image) -> Image.Image:
        a = self.augment or {}
        if a.get("hflip") and random.random() < 0.5:
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if a.get("rotate_deg"):
            img = img.rotate(random.uniform(-a["rotate_deg"], a["rotate_deg"]), resample=Image.Resampling.BILINEAR)
        if a.get("scale"):
            s = random.uniform(*a["scale"])
            w, h = img.size
            cw, ch = int(w * s), int(h * s)
            x, y = random.randint(0, w - cw), random.randint(0, h - ch)
            img = img.crop((x, y, x + cw, y + ch))
        if a.get("brightness"):
            img = ImageEnhance.Brightness(img).enhance(1 + random.uniform(-a["brightness"], a["brightness"]))
        if a.get("contrast"):
            img = ImageEnhance.Contrast(img).enhance(1 + random.uniform(-a["contrast"], a["contrast"]))
        return img

    def __getitem__(self, i: int) -> tuple[torch.Tensor, int]:
        row = self.rows[i]
        with Image.open(row["path"]) as im:
            img = im.convert("RGB")
        if self.augment:
            img = self._augment(img)
        x = to_model_input(img, self.input_size, self.mean, self.std)
        return torch.from_numpy(np.ascontiguousarray(x)), self.index[row["label"]]
