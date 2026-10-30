"""Generate synthetic images so the pipeline can run end to end without real data.

    python -m src.make_placeholder_data
"""

from __future__ import annotations

import csv
import hashlib

import numpy as np
from PIL import Image

from src.common import ML_ROOT, load_pack_conditions
from src.dataset import MANIFEST_COLUMNS

PER_CLASS = 24


def main() -> None:
    ids = load_pack_conditions("../packs/eye")["ids"]
    root = ML_ROOT / "data" / "placeholder"
    images = root / "images"
    images.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    rows = []
    for k, cid in enumerate(ids):
        base = np.array([(k * 53) % 256, (k * 97) % 256, (k * 151) % 256], dtype=np.float32)
        for j in range(PER_CLASS):
            arr = np.clip(base + rng.normal(0, 25, size=(96, 96, 3)), 0, 255).astype(np.uint8)
            name = f"{cid}_{j:03d}.jpg"
            Image.fromarray(arr).save(images / name, quality=90)
            subject = hashlib.sha256(f"{cid}-{j // 2}".encode()).hexdigest()[:12]
            rows.append(
                {
                    "image_id": name, "subject_hash": subject, "view": "right_eye" if j % 2 else "left_eye",
                    "label": cid, "label_source": "synthetic", "source_dataset": "placeholder",
                    "site": f"site{j % 3}", "device_model": "synthetic", "capture": "camera",
                    "consent_ref": "synthetic-no-patient",
                }
            )  # fmt: skip
    with open(root / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} synthetic images to {images}")


if __name__ == "__main__":
    main()
