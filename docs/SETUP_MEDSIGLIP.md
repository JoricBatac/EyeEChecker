# Setting up MedSigLIP (zero-shot classifier, stage A)

MedSigLIP is Google's medical image-text encoder from the MedGemma / Health AI Developer Foundations (HAI-DEF)
family. ScanAssist uses it two ways:

- **Backend** (`CLASSIFIER=zero_shot`): scores each encounter's photos against the condition prompts in
  `packs/eye/conditions.json` and stores the result in `reveal_after` mode for design partners.
- **ml/** (`src/zero_shot.py`): Test 2 baseline on your frozen labeled test set, and as a frozen encoder for
  the stage B linear probe (`src/train_probe.py --backbone medsiglip`).

The model is gated, so you need a Hugging Face account and a token. Nothing else is required.

## 1. Get access (about 5 minutes, one time)

1. Create an account at https://huggingface.co/join.
2. Open https://huggingface.co/google/medsiglip-448, read the HAI-DEF terms of use and click
   **Agree and access repository**. Access is usually granted immediately.
   - Before commercial launch, have the lawyer review the HAI-DEF terms (PRD 10.2).
3. Create a token at https://huggingface.co/settings/tokens: **Create new token**, type **Read**.
   Copy it (`hf_...`). Treat it like a password.

## 2. Put the token where the code looks for it

Create `.env` in the repo root (it is git-ignored) from the template:

```
copy .env.example .env        (Windows)    or    cp .env.example .env
```

and set:

```
HF_TOKEN=hf_your_token_here
CLASSIFIER=zero_shot
```

For the `ml/` scripts, set it in your shell instead (they don't read `.env`):

```powershell
$env:HF_TOKEN = "hf_your_token_here"        # PowerShell
```

## 3. Install the ML dependencies

**Backend** (adds PyTorch CPU, transformers, onnxruntime; about 1 GB):

```powershell
cd backend
.venv\Scripts\python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
.venv\Scripts\python -m pip install -e ".[ml]"
```

**ml/** already has these installed (`ml/.venv`, from `ml/requirements.txt`).

## 4. First run downloads the weights

The first analysis downloads ~3.5 GB into `%USERPROFILE%\.cache\huggingface` (or `~/.cache/huggingface`).
Later runs load from cache. Expect a few seconds per encounter on a laptop CPU, and about 1 to 3 seconds on
the Oracle ARM VM.

Quick check that access works:

```powershell
cd ml
$env:HF_TOKEN = "hf_..."
.venv\Scripts\python -c "from transformers import AutoModel; AutoModel.from_pretrained('google/medsiglip-448'); print('ok')"
```

A `401` or `GatedRepoError` means step 1.2 or the token is missing.

## 5. Run Test 2 (zero-shot baseline) on your labeled photos

1. Put images under `ml/data/eye/images/` (or point `ML_EXTERNAL_DATA_ROOT` at another folder). Never put
   patient photos in notebooks, chat tools or the app's storage.
2. Write `ml/data/eye/frozen_test.csv` with the manifest columns
   `image_id, subject_hash, view, label, label_source, source_dataset, site, device_model, capture, consent_ref`
   (`label` must be a condition ID from `packs/eye/conditions.json`). For a folder-per-class dataset use
   `python -m src.import_folder ...` to generate it.
3. Run:
   ```powershell
   cd ml
   .venv\Scripts\python -m src.zero_shot --config configs/eye.yaml
   ```
   Results land in `ml/runs/<timestamp>-zeroshot-eye/` (`evaluation.md`, `probabilities.csv`).

Tune the wording of `zero_shot_prompts` in `packs/eye/conditions.json` against this report; the backend uses
exactly the same prompts.

## 6. Production

On the launch VM, put `HF_TOKEN` and `CLASSIFIER=zero_shot` in `infra/launch/.env`; the backend image is built
with `INSTALL_ML=true`. Pin and mirror the weights to your own bucket before onboarding partners (PRD 12.8).
