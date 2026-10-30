# TODO

Scope (2026-10-30): mobile-only, storage-free diagnosis assistant. Web app and record-keeping backend are parked.

## 1. Fix first

- [ ] **Commit and push to GitHub.** Nothing from the build is committed yet. `.env`, venvs, `ml/data`, `ml/runs`
      and `apps/mobile/.env` are git-ignored; double-check before the first push.
- [ ] **Wire the trained probe into the app** (biggest accuracy gain). Zero-shot MedSigLIP over 12 conditions gives
      flat 10-15% scores; the linear probe scored 96% top-1 on normal / conjunctivitis / cataract / uveitis.
  - Export the probe to ONNX from `ml/` (coordinate with the ml session; its config is marked research-only).
  - Backend: accept a model that covers only some pack conditions, and map the merged "conjunctivitis" class.
  - Label it in the app as a research model; keep zero-shot for the uncovered conditions or show none.
  - Re-check the 96% after `near_duplicates` finishes (possible train/test leakage).
- [ ] **Restart the backend** to ship the "Other possibilities" list (`others` field). Avoid doing it while heavy
      ml jobs run: loading MedSigLIP takes ~3.3 GB RAM and briefly froze the PC.
- [ ] **Confirm on a real phone**: startup crash fix, iOS header overlap fix, photo upload (FormData) fix,
      follow-up questions, results photo strip.
- [ ] **Clinical review** of draft content in `packs/eye`: red-flag rules, `visual_features` / `evidence`
      explanations, management library, Filipino translations. Nothing has been reviewed by a clinician yet.

## 2. Demo setup (blocked: Oracle signup needs a credit card)

- [ ] Oracle Cloud Always Free account, home region **Singapore (ap-singapore-1)**.
- [ ] Deploy backend with `infra/launch` (arm64 VM, Caddy HTTPS, `CLASSIFIER=zero_shot` or the probe).
- [ ] Demo access codes: `python -m scripts.create_access_code "<name>"` on the server.
- [ ] Android APK via EAS Build pointed at the cloud backend (needs a free Expo account).
      iPhone testers need TestFlight ($99/yr Apple developer account); until then demo on your own phone.
- [ ] Demo with dataset/sample photos only; no real patients until consent text and data agreements exist.

## 3. Skin pack (start small)

The platform already loads packs; `packs/skin` is a disabled placeholder.

- [ ] Pick a first condition list (5-8 common, photographable conditions, e.g. acne, eczema/dermatitis,
      fungal infection (tinea), scabies, impetigo, psoriasis, urticaria, plus "other / not assessable").
      Needs a dermatologist to own it, like the eye pack's clinical advisor.
- [ ] Write the pack files: `conditions.json` (with `zero_shot_prompts`, `visual_features`, `evidence`),
      `capture_protocol.json` (framing, distance, lighting, scale reference), `exam_form.schema.json`
      (duration, itch, spread, fever, location), `ruleset.v1.json` red flags (e.g. rapidly spreading redness
      with fever, blistering with mucosal involvement, a changing mole), templates and EN/FIL content.
- [ ] Mobile: let the user choose Eye or Skin on "New check" (the app currently uses the first enabled pack).
- [ ] Zero-shot baseline on a public skin dataset first, then a probe. Check licensing, and that the data
      covers darker skin tones (Fitzpatrick IV-VI) common in the Philippines.

## Parked

- Web dashboard and internal console (`apps/web`).
- Record-keeping API (patients, encounters, sign-off, referral queue) and report PDFs.
- Self-hosted MedGemma report polishing (`infra/llm`).
