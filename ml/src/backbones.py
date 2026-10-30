"""Image encoders behind one interface, so MedSigLIP and CNN baselines are benchmarked the same way (PRD 10.2)."""

from __future__ import annotations

from typing import Any

import torch
from torch import nn

from src.common import hf_token


class Encoder(nn.Module):
    def __init__(self, name: str, body: nn.Module, dim: int, cfg: dict[str, Any]):
        super().__init__()
        self.name, self.body, self.dim = name, body, dim
        self.input_size: int = cfg["input_size"]
        self.mean: list[float] = cfg["mean"]
        self.std: list[float] = cfg["std"]
        # Identifies the weights, so cached embeddings are never reused across different models.
        self.weights_id: str = cfg.get("model_id") or cfg.get("name") or cfg["kind"]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.body(x)


def as_tensor(features: Any) -> torch.Tensor:
    """transformers 5 returns a model output from get_*_features; 4.x returned the tensor directly."""
    return features if isinstance(features, torch.Tensor) else features.pooler_output


class _MedSigLIPVision(nn.Module):
    def __init__(self, model: nn.Module):
        super().__init__()
        self.model = model

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return as_tensor(self.model.get_image_features(pixel_values=x))


class _Tiny(nn.Module):
    """Small random CNN for pipeline tests on placeholder data only."""

    def __init__(self, dim: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 16, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(32, dim, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
        )  # fmt: skip

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def build_encoder(name: str, cfg: dict[str, Any]) -> Encoder:
    kind = cfg["kind"]
    if kind == "medsiglip":
        from transformers import AutoModel

        model = AutoModel.from_pretrained(cfg["model_id"], token=hf_token())
        return Encoder(name, _MedSigLIPVision(model), model.config.vision_config.hidden_size, cfg)
    if kind == "timm":
        import timm

        body = timm.create_model(cfg["name"], pretrained=True, num_classes=0)
        return Encoder(name, body, body.num_features, cfg)
    if kind == "tiny":
        torch.manual_seed(0)
        return Encoder(name, _Tiny(), 64, cfg)
    raise ValueError(f"unknown backbone kind {kind}")


class Classifier(nn.Module):
    """Encoder + linear head; outputs logits. This is what gets exported to ONNX."""

    def __init__(self, encoder: Encoder, num_classes: int, head: nn.Linear | None = None):
        super().__init__()
        self.encoder = encoder
        self.head = head or nn.Linear(encoder.dim, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.encoder(x))
