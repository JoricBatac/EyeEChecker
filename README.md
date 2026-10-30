# EyeEChecker (ScanAssist)

Mobile clinical decision support for eye conditions. A clinician photographs the eye, fills a short exam,
sees red-flag alerts immediately, records their own impression, then compares it with a MedSigLIP AI ranking
and shares a referral letter or patient handout as a PDF.

**Nothing about the patient is stored.** Photos are analyzed in memory on the server and deleted from the phone
when the check ends; the patient's name never leaves the phone. The server keeps only clinic access codes and
anonymous AI-vs-clinician scores (condition IDs and probabilities) used to measure accuracy per condition.

## Layout

| Path | What |
|---|---|
| `apps/mobile` | Expo app (the product) |
| `backend` | FastAPI: assist API (`/v1/assist/*`), rules engine, MedSigLIP inference, report templates |
| `packs/eye` | Everything eye-specific: conditions, exam form, red-flag rules, management, templates, content |
| `ml` | Training pipeline (zero-shot eval, linear probe, fine-tune, ONNX export) |
| `eval` | Report-writer test harness and the MedSigLIP spot-check page (`eval/medsiglip_check`, port 3010) |
| `packages/shared_ts` | TypeScript API types and client |
| `infra` | Launch stack (single ARM VM) and self-hosted MedGemma |
| `apps/web` | Clinic dashboard / internal console: **parked** |

The record-keeping API (patients, encounters, sign-off, referral queue) is parked in the backend: still tested,
not used by the app.

## Run it locally

1. **Backend** (Python 3.12):
   ```powershell
   cd backend
   python -m venv .venv
   .venv\Scripts\python -m pip install -e ..\packages\core_py -e ".[dev]"
   .venv\Scripts\python -m scripts.create_access_code "My Clinic"      # prints the code once
   .venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Uses SQLite by default. `CLASSIFIER=stub` in `.env` gives fake AI scores; for real MedSigLIP see
   [docs/SETUP_MEDSIGLIP.md](docs/SETUP_MEDSIGLIP.md) (`CLASSIFIER=zero_shot`).
2. **Mobile** (Node 20+, Expo Go on your phone, same Wi-Fi):
   ```powershell
   cd apps\mobile
   npm install
   $env:EXPO_PUBLIC_API_URL = "http://<your-PC-LAN-IP>:8000"
   npx expo start
   ```
   Scan the QR code with Expo Go, enter the access code and your name on first launch.
   Windows may ask to allow Python through the firewall for port 8000.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest        # safety and privacy guardrails
.venv\Scripts\python -m scripts.assist_metrics   # AI vs clinician agreement from anonymous scores
```

Follows the Clinical Decision Support PRD v0.5 safety rules, with the storage-free, mobile-only scope chosen on
2026-10-30.
