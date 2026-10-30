"""Export encoder + head to ONNX with the metadata.json the backend's OnnxClassifier reads."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from src.backbones import Classifier


def export(
    model: Classifier,
    out_dir: Path,
    *,
    pack_id: str,
    model_version: str,
    condition_ids: list[str],
    temperature: float,
    thresholds: dict[str, float],
    data_hash: str,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    model = model.eval()
    enc = model.encoder
    dummy = torch.randn(1, 3, enc.input_size, enc.input_size)
    onnx_path = out_dir / "model.onnx"
    torch.onnx.export(
        model,
        (dummy,),
        str(onnx_path),
        input_names=["pixel_values"],
        output_names=["logits"],
        dynamic_axes={"pixel_values": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    meta: dict[str, Any] = {
        "pack_id": pack_id,
        "model_version": model_version,
        "condition_ids": condition_ids,
        "input_size": enc.input_size,
        "mean": enc.mean,
        "std": enc.std,
        "temperature": temperature,
        "thresholds": thresholds,
        "dataset_hash": data_hash,
        "backbone": enc.name,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    _verify(model, onnx_path, dummy)
    print(f"exported {onnx_path}")
    return onnx_path


def _verify(model: Classifier, onnx_path: Path, dummy: torch.Tensor) -> None:
    import onnxruntime as ort

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    batch = torch.cat([dummy, dummy * 0.5])
    with torch.no_grad():
        expected = model(batch).numpy()
    got = session.run(None, {"pixel_values": batch.numpy()})[0]
    if not np.allclose(expected, got, atol=1e-3):
        raise RuntimeError("ONNX output does not match PyTorch output")
