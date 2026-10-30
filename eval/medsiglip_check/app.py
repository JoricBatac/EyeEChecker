"""Local page for spot-checking MedSigLIP zero-shot predictions against a known diagnosis.

Upload eye photos, pick the diagnosis you expect, and see whether MedSigLIP ranks it first.
Scoring mirrors ZeroShotClassifier in backend/app/modules/inference/classifiers.py.

Run:  python eval/medsiglip_check/app.py   then open http://127.0.0.1:3010
Photos stay in memory only and are never written to disk.
"""

from __future__ import annotations

import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import torch
from PIL import Image, ImageOps
from transformers import AutoModel, AutoProcessor

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CONDITIONS_FILE = REPO_ROOT / "packs" / "eye" / "conditions.json"
MODEL_ID = os.environ.get("MEDSIGLIP_MODEL_ID", "google/medsiglip-448")
HOST, PORT = "127.0.0.1", 3010
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split(" #", 1)[0].strip().strip("'\"")
    return values


def hf_token() -> str | None:
    env = {**read_env_file(REPO_ROOT / ".env"), **os.environ}
    for key in ("HUGGINGFFACE_ACCESSTOKEN", "HF_TOKEN"):
        if env.get(key):
            return env[key]
    return None


def as_tensor(features) -> torch.Tensor:
    # transformers 5 returns a model output from get_*_features; 4.x returned the tensor directly.
    return features if isinstance(features, torch.Tensor) else features.pooler_output


class Scorer:
    def __init__(self, token: str | None):
        conditions = json.loads(CONDITIONS_FILE.read_text(encoding="utf-8"))["conditions"]
        self.conditions = [c for c in conditions if c.get("classifiable", True)]
        print(f"loading {MODEL_ID} (first run downloads ~3.5 GB)...", flush=True)
        self.model = AutoModel.from_pretrained(MODEL_ID, token=token).eval()
        self.processor = AutoProcessor.from_pretrained(MODEL_ID, token=token)

        embeddings = []
        with torch.no_grad():
            for c in self.conditions:
                tok = self.processor(text=c["zero_shot_prompts"], padding="max_length", return_tensors="pt")
                emb = as_tensor(self.model.get_text_features(**tok))
                emb = emb / emb.norm(dim=-1, keepdim=True)
                mean = emb.mean(dim=0)
                embeddings.append(mean / mean.norm())
        self.text_emb = torch.stack(embeddings)

    def score(self, image: Image.Image) -> list[dict]:
        with torch.no_grad():
            inputs = self.processor(images=[image], return_tensors="pt")
            img = as_tensor(self.model.get_image_features(**inputs))
            img = img / img.norm(dim=-1, keepdim=True)
            logits = img @ self.text_emb.T * self.model.logit_scale.exp() + self.model.logit_bias
            probs = torch.softmax(logits, dim=-1)[0].tolist()
        ranked = [
            {"id": c["id"], "name": c["name"]["en"], "prob": round(p, 4)}
            for c, p in zip(self.conditions, probs, strict=True)
        ]
        return sorted(ranked, key=lambda r: r["prob"], reverse=True)


SCORER: Scorer | None = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, "text/html; charset=utf-8", (HERE / "index.html").read_bytes())
        elif path == "/conditions":
            items = [{"id": c["id"], "name": c["name"]["en"]} for c in SCORER.conditions]
            self._json(200, items)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/check":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_UPLOAD_BYTES:
            return self._json(400, {"error": "photo missing or larger than 20 MB"})
        try:
            with Image.open(io.BytesIO(self.rfile.read(length))) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
        except Exception:
            return self._json(400, {"error": "could not read that file as an image"})

        ranked = SCORER.score(image)
        expected = parse_qs(url.query).get("expected", [""])[0]
        rank = next((i + 1 for i, r in enumerate(ranked) if r["id"] == expected), None)
        self._json(200, {"ranked": ranked, "expected": expected or None, "expected_rank": rank,
                         "correct": rank == 1 if expected else None})

    def _json(self, status: int, body) -> None:
        self._send(status, "application/json", json.dumps(body).encode())

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main() -> None:
    global SCORER
    token = hf_token()
    if not token:
        print("warning: no HUGGINGFFACE_ACCESSTOKEN or HF_TOKEN found in .env; gated model download will fail")
    SCORER = Scorer(token)
    print(f"ready: open http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
