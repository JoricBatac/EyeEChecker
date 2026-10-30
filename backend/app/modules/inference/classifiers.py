"""Classifier implementations behind one interface (PRD 10.2).

New models are swapped in per pack by changing the pack's `model` reference (or CLASSIFIER env), with no app changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image
from scanassist_core.preprocess import softmax, to_model_input

from app.core.config import get_settings
from app.modules.packs.loader import Pack

log = logging.getLogger(__name__)


class Classifier(Protocol):
    kind: str
    model_version: str
    condition_ids: list[str]

    def predict(self, images: list[Image.Image]) -> dict[str, float]:
        """Probabilities per condition, averaged over the encounter's photos."""
        ...


class StubClassifier:
    """Deterministic fake probabilities for development and tests. Never use with patients."""

    kind = "stub"

    def __init__(self, condition_ids: list[str]):
        self.condition_ids = condition_ids
        self.model_version = "stub-0"

    def predict(self, images: list[Image.Image]) -> dict[str, float]:
        digest = hashlib.sha256(b"".join(img.tobytes()[:4096] for img in images)).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        probs = rng.dirichlet(np.ones(len(self.condition_ids)) * 0.5)
        return {cid: round(float(p), 4) for cid, p in zip(self.condition_ids, probs, strict=True)}


def _as_tensor(features):  # type: ignore[no-untyped-def]
    """transformers 5 returns a model output from get_*_features; 4.x returned the tensor directly."""
    return features if hasattr(features, "norm") else features.pooler_output


class ZeroShotClassifier:
    """MedSigLIP image-text matching against the pack's condition prompts (stage A)."""

    kind = "zero_shot"

    def __init__(self, pack: Pack, model_id: str, hf_token: str | None, version: str):
        import torch
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        self.model_version = version
        self.condition_ids = pack.classifiable_ids
        log.info("loading %s (first run downloads ~3.5 GB)", model_id)
        self.model = AutoModel.from_pretrained(model_id, token=hf_token).eval()
        self.processor = AutoProcessor.from_pretrained(model_id, token=hf_token)

        embeddings = []
        with torch.no_grad():
            for cid in self.condition_ids:
                prompts = pack.condition(cid).zero_shot_prompts  # type: ignore[union-attr]
                tok = self.processor(text=prompts, padding="max_length", return_tensors="pt")
                emb = _as_tensor(self.model.get_text_features(**tok))
                emb = emb / emb.norm(dim=-1, keepdim=True)
                mean = emb.mean(dim=0)
                embeddings.append(mean / mean.norm())
        self.text_emb = torch.stack(embeddings)

    def predict(self, images: list[Image.Image]) -> dict[str, float]:
        torch = self._torch
        with torch.no_grad():
            inputs = self.processor(images=images, return_tensors="pt")
            img = _as_tensor(self.model.get_image_features(**inputs))
            img = img / img.norm(dim=-1, keepdim=True)
            logits = img @ self.text_emb.T * self.model.logit_scale.exp() + self.model.logit_bias
            probs = torch.softmax(logits, dim=-1).mean(dim=0).numpy()
        return {cid: round(float(p), 4) for cid, p in zip(self.condition_ids, probs, strict=True)}


class OnnxClassifier:
    """Trained model exported by ml/src/export_onnx.py (stages B and C)."""

    kind = "onnx"

    def __init__(self, model_dir: Path):
        import onnxruntime as ort

        meta = json.loads((model_dir / "metadata.json").read_text())
        self.meta = meta
        self.model_version = meta["model_version"]
        self.condition_ids = meta["condition_ids"]
        self.session = ort.InferenceSession(str(model_dir / "model.onnx"), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, images: list[Image.Image]) -> dict[str, float]:
        m = self.meta
        batch = np.stack([to_model_input(img, m["input_size"], m["mean"], m["std"]) for img in images])
        logits = self.session.run(None, {self.input_name: batch})[0]
        probs = softmax(logits, m.get("temperature", 1.0)).mean(axis=0)
        return {cid: round(float(p), 4) for cid, p in zip(self.condition_ids, probs, strict=True)}


@lru_cache
def get_classifier(pack_id: str) -> Classifier | None:
    from app.modules.packs.loader import get_pack

    pack = get_pack(pack_id)
    if pack is None:
        return None
    s = get_settings()
    kind = s.classifier or pack.model.kind
    try:
        if kind == "stub":
            return StubClassifier(pack.classifiable_ids)
        if kind == "zero_shot":
            return ZeroShotClassifier(pack, s.medsiglip_model_id, s.hf_token, pack.model.version)
        if kind == "onnx":
            assert pack.model.onnx_dir, "pack model.onnx_dir is not set"
            return OnnxClassifier(s.model_dir / pack.model.onnx_dir)
    except Exception:
        # The app stays useful without AI (PRD 3): log and continue with rules only.
        log.exception("classifier %s for pack %s failed to load; AI disabled", kind, pack_id)
    return None
