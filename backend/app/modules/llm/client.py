"""Optional report polishing via self-hosted MedGemma (vLLM, OpenAI-compatible API).

Any failure (off, slow, error) returns None and the template draft stays. Nothing blocks sign-off.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.modules.llm.payload import PLACEHOLDERS, AllowlistedPayload

log = logging.getLogger(__name__)

# Shared with eval/report_writer so Test 1 evaluates exactly the production prompt.
SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8").strip()
assert all(p in SYSTEM_PROMPT for p in PLACEHOLDERS)


def polish(payload: AllowlistedPayload) -> str | None:
    s = get_settings()
    if s.llm_provider != "medgemma_selfhosted" or not s.llm_base_url:
        return None
    try:
        resp = httpx.post(
            f"{s.llm_base_url.rstrip('/')}/v1/chat/completions",
            json={
                "model": s.llm_model,
                "temperature": 0.2,
                "max_tokens": 1200,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": payload.model_dump_json()},
                ],
            },
            timeout=s.llm_timeout_ms / 1000,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return text.strip() or None
    except Exception as exc:  # timeout, connection refused, bad response
        log.warning("LLM polishing unavailable, keeping template: %s", type(exc).__name__)
        return None
