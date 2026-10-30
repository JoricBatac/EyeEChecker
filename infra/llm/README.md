# Self-hosted MedGemma (Phase 2, PRD 12.8)

One GPU VM with an NVIDIA L4 (24 GB) in Singapore running vLLM with MedGemma 4B (instruction-tuned).
No public endpoint: only the backend reaches it, over a private network or WireGuard.

## Setup

1. Accept Google's Health AI Developer Foundations terms on the model page
   (https://huggingface.co/google/medgemma-4b-it) and create a read token.
2. On the GPU VM (Ubuntu + NVIDIA driver + Docker with the NVIDIA container toolkit):
   ```
   export HF_TOKEN=hf_...
   ./download_model.sh            # mirrors pinned weights to /opt/models
   docker compose up -d
   ```
3. Install the clinic-hours schedule (07:00 to 21:00 Asia/Manila):
   `sudo cp medgemma-*.service medgemma-*.timer /etc/systemd/system/ && sudo systemctl enable --now medgemma-start.timer medgemma-stop.timer`
4. On the backend: `LLM_PROVIDER=medgemma_selfhosted`, `LLM_BASE_URL=http://<private-ip>:8000`.
   Turn polishing on per organization (`PUT /v1/org/settings {"llm_polish": true}`).

Outside clinic hours or on any error, reports use templates and nothing blocks (PRD 10.4).
Request logging is disabled (`--disable-log-requests`); only latency/error metrics are kept.
