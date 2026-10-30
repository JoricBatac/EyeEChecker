"""What clinic users may see of a model result. Single choke point for the shadow / reveal_after guardrails."""

from app.modules.encounters.models import AIResult
from app.modules.packs.loader import Pack

BEFORE_ASSESSMENT = frozenset({"visible"})
AFTER_ASSESSMENT = frozenset({"visible", "reveal_after"})


def likelihood_band(pack: Pack, p: float) -> str:
    if p >= pack.likelihood_bands.get("high", 0.6):
        return "high"
    if p >= pack.likelihood_bands.get("moderate", 0.3):
        return "moderate"
    return "low"


def allowed_conditions(ai: AIResult, allowed_states: frozenset[str]) -> list[str]:
    return [cid for cid, state in ai.condition_states.items() if state in allowed_states]


def suggestions(pack: Pack, ai: AIResult, allowed_states: frozenset[str], top_k: int = 3) -> list[dict]:
    allowed = set(allowed_conditions(ai, allowed_states))
    ranked = sorted(
        ((cid, p) for cid, p in ai.probabilities.items() if cid in allowed), key=lambda x: x[1], reverse=True
    )[:top_k]
    out = []
    for cid, p in ranked:
        c = pack.condition(cid)
        out.append(
            {
                "condition_id": cid,
                "name": c.name if c else {"en": cid},
                "likelihood": likelihood_band(pack, p),
                "probability": p,
                "default_urgency": c.default_urgency if c else None,
            }
        )
    return out


def label(ai: AIResult) -> dict:
    return {
        "label": "AI suggestion, for clinician review",
        "model_version": ai.model_version,
        "ai_result_id": ai.id,
    }
