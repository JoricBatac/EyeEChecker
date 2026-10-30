# Evaluation harness (PRD 10.7)

## Test 1: report writer, MedGemma 4B vs 27B

Payloads are de-identified (same allowlisted schema as production, `backend/app/modules/llm/payload.py`),
so free notebook GPUs (Kaggle, Colab) or a GPU rented for a day are fine.

1. Build 25 to 30 cases as JSON lines in the allowlisted format (see `report_writer/cases.example.jsonl`):
   common conditions, emergencies, suspected cataract, at least one pediatric case. No names, no photos.
2. Serve both models with vLLM (OpenAI-compatible), e.g. on a Kaggle/Colab GPU:
   `vllm serve google/medgemma-4b-it --port 8001` and `vllm serve google/medgemma-27b-text-it --port 8002`
   (27B needs ~60 GB VRAM, or use a quantized build).
3. `cd eval/report_writer`
4. `python generate.py --cases cases.jsonl --endpoint 4b=http://HOST:8001 --endpoint 27b=http://HOST:8002`
5. `python fact_check.py --cases cases.jsonl` (any invented condition, medication or dose fails)
6. `python review_sheet.py`, then send `out/review_sheet.csv` to design partner doctors (blind).
7. `python review_sheet.py --decide out/review_sheet_filled.csv` applies the agreed decision rule.

Only `httpx` is needed (`pip install httpx`).

## Test 2: zero-shot classifier baseline

Run on your own machine or VM. **Never upload patient photos to notebook services or chat tools.**

```
cd ml
python -m src.zero_shot --config configs/eye.yaml        # uses data/eye/frozen_test.csv
```

The frozen test set stays test-only: `train_probe.py` and `finetune.py` exclude its subjects automatically.
