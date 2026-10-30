"""On-disk cache of frozen-encoder embeddings, keyed by image content and encoder settings.

Embedding is the slow part of a linear probe (about an hour on CPU for ~1,200 photos with MedSigLIP);
the head trains in seconds. With the cache, relabeling, re-splitting or retuning the probe reuses
every embedding already computed. The cache lives under ml/data/ because embeddings are derived
from the training photos and follow the same handling rules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from scanassist_core.preprocess import to_model_input

from src.backbones import Encoder
from src.common import ML_ROOT

CACHE_ROOT = ML_ROOT / "data" / ".embedding_cache"


def cache_dir(encoder: Encoder) -> Path:
    settings = {"weights": encoder.weights_id, "size": encoder.input_size, "mean": encoder.mean, "std": encoder.std}
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:12]
    d = CACHE_ROOT / f"{encoder.name}-{key}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(json.dumps(settings, indent=2))
    return d


def image_key(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


@torch.no_grad()
def embed_rows(encoder: Encoder, rows: list[dict[str, Any]], batch_size: int = 16) -> np.ndarray:
    """Embeddings for rows[i]["path"], in order. Only images not already cached go through the encoder."""
    d = cache_dir(encoder)
    keys = [image_key(r["path"]) for r in rows]
    todo = sorted({k: i for i, k in enumerate(keys) if not (d / f"{k}.npy").exists()}.values())
    if todo:
        print(f"embedding {len(todo)} new images ({len(rows) - len(todo)} cached)", flush=True)
    for start in range(0, len(todo), batch_size):
        idx = todo[start : start + batch_size]
        batch = []
        for i in idx:
            with Image.open(rows[i]["path"]) as im:
                img = im.convert("RGB")
            batch.append(torch.from_numpy(to_model_input(img, encoder.input_size, encoder.mean, encoder.std)))
        for i, e in zip(idx, encoder(torch.stack(batch)).numpy(), strict=True):
            np.save(d / f"{keys[i]}.npy", e)
        print(f"  {min(start + batch_size, len(todo))}/{len(todo)}", flush=True)
    return np.stack([np.load(d / f"{k}.npy") for k in keys])
