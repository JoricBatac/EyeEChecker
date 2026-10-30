"""Image preprocessing shared by the backend (inference) and ml/ (training).

Keeping one implementation guarantees a model sees the same pixels in training and in production.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageOps


def sanitize_photo(data: bytes, max_long_edge: int = 1600, quality: int = 90) -> tuple[bytes, int, int]:
    """Apply EXIF orientation, drop all metadata (EXIF, GPS, ICC), resize, re-encode as JPEG."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((max_long_edge, max_long_edge), Image.Resampling.LANCZOS)
        # Copy pixels into a fresh image so no metadata survives.
        clean = Image.new("RGB", img.size)
        clean.paste(img)
        out = io.BytesIO()
        clean.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue(), clean.width, clean.height


def load_rgb(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as img:
        return img.convert("RGB")


def to_model_input(
    img: Image.Image,
    input_size: int,
    mean: Sequence[float],
    std: Sequence[float],
) -> np.ndarray:
    """Center-crop to square, resize, normalize. Returns float32 array shaped (3, H, W).

    No hue or color changes: color is diagnostic for eye and skin.
    """
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize(
        (input_size, input_size), Image.Resampling.BICUBIC
    )
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - np.asarray(mean, dtype=np.float32)) / np.asarray(std, dtype=np.float32)
    return arr.transpose(2, 0, 1).copy()


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits / max(temperature, 1e-6)
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)
