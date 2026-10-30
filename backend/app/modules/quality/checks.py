"""Image quality checks (FR-11). Thresholds and tips come from the pack's capture protocol."""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.modules.packs.loader import CaptureProtocol

MIN_SHORT_EDGE = 480


def _laplacian_variance(gray: np.ndarray) -> float:
    lap = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return float(lap.var())


def check_quality(img: Image.Image, protocol: CaptureProtocol, view_id: str) -> dict:
    thresholds = dict(protocol.quality)
    view = next((v for v in protocol.views if v.id == view_id), None)
    if view:
        thresholds.update(view.quality_overrides)

    small = img.convert("L")
    small.thumbnail((512, 512))
    gray = np.asarray(small, dtype=np.float32)

    metrics = {
        "sharpness": round(_laplacian_variance(gray), 1),
        "brightness": round(float(gray.mean()), 1),
        "glare_fraction": round(float((gray >= 250).mean()), 4),
        "short_edge": min(img.size),
    }
    issues = []
    if metrics["short_edge"] < MIN_SHORT_EDGE:
        issues.append("too_small")
    if metrics["sharpness"] < thresholds.get("min_sharpness", 0):
        issues.append("blurry")
    if metrics["brightness"] < thresholds.get("min_brightness", 0):
        issues.append("too_dark")
    if metrics["brightness"] > thresholds.get("max_brightness", 255):
        issues.append("too_bright")
    if metrics["glare_fraction"] > thresholds.get("max_glare_fraction", 1):
        issues.append("glare")

    return {
        "ok": not issues,
        "metrics": metrics,
        "issues": [{"code": code, "tip": protocol.retake_tips.get(code, {})} for code in issues],
    }
