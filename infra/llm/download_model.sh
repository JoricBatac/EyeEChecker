#!/usr/bin/env bash
# Download pinned MedGemma weights once (gated: accept Google's terms first). Mirror to your bucket afterwards.
set -euo pipefail
: "${HF_TOKEN:?set HF_TOKEN}"
MODEL=${MODEL:-google/medgemma-4b-it}
REVISION=${REVISION:-main}   # pin to a commit hash once Test 1 picks the model
pip install -q "huggingface_hub[cli]"
huggingface-cli download "$MODEL" --revision "$REVISION" --local-dir "/opt/models/$(basename "$MODEL")" --token "$HF_TOKEN"
