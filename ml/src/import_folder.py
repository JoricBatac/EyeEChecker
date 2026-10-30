"""Write a training manifest for a dataset laid out as one folder per class.

    python -m src.import_folder --source "<dir>" --out data/eyeproject2/manifest.csv \
        --map Cataract=lens_opacity_cataract --map Normal=normal ... \
        --source-dataset eyeproject2 --consent-ref "<reference>"

Images are not copied: the manifest points into --source, which must be under ml/data/ or ML_EXTERNAL_DATA_ROOT.
Datasets without patient IDs get one subject per distinct image (by content hash), so exact duplicates
always share a split. Near-duplicates of the same patient can still leak across splits.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
from pathlib import Path

from src.common import resolve
from src.dataset import MANIFEST_COLUMNS, check_image_root

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="folder containing one subfolder per class")
    ap.add_argument("--out", required=True, help="manifest path to write")
    ap.add_argument("--map", action="append", required=True, metavar="FOLDER=LABEL")
    ap.add_argument("--source-dataset", required=True)
    ap.add_argument("--consent-ref", required=True, help="where consent/licensing for this dataset is recorded")
    ap.add_argument("--label-source", default="folder_name")
    ap.add_argument(
        "--exclude", action="append", default=[], metavar="GLOB",
        help="skip matching file names, e.g. 'aug_*' for pre-augmented copies that would leak across splits",
    )  # fmt: skip
    args = ap.parse_args()

    root = check_image_root(Path(args.source))
    mapping = dict(m.split("=", 1) for m in args.map)
    missing = [f for f in mapping if not (root / f).is_dir()]
    if missing:
        ap.error(f"class folders not found: {missing}")
    unmapped = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name not in mapping)
    if unmapped:
        ap.error(f"folders without a --map entry: {unmapped}")

    rows, seen, excluded = [], {}, 0
    for folder, label in mapping.items():
        for f in sorted((root / folder).iterdir()):
            if f.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if any(fnmatch.fnmatch(f.name, g) for g in args.exclude):
                excluded += 1
                continue
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            if digest in seen:
                print(f"skipping duplicate {folder}/{f.name} (same as {seen[digest]})")
                continue
            seen[digest] = f"{folder}/{f.name}"
            rows.append(
                {
                    "image_id": f"{folder}/{f.name}", "subject_hash": digest[:16], "view": "unknown",
                    "label": label, "label_source": args.label_source, "source_dataset": args.source_dataset,
                    "site": args.source_dataset, "device_model": "unknown", "capture": "unknown",
                    "consent_ref": args.consent_ref,
                }
            )  # fmt: skip

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    counts = {label: sum(r["label"] == label for r in rows) for label in mapping.values()}
    print(f"wrote {len(rows)} rows to {out}: {counts} ({excluded} excluded by --exclude)")


if __name__ == "__main__":
    main()
