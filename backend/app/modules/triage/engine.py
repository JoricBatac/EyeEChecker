"""Rules engine (PRD 9). Runs on every encounter whether or not a model exists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core import expr
from app.modules.packs.loader import URGENCY_ORDER, Pack


@dataclass
class Alert:
    rule_id: str
    severity: str
    message: dict[str, str]
    source: str  # rules | model
    shown: bool
    referral: bool = False
    subject: str = ""


@dataclass
class TriageResult:
    alerts: list[Alert] = field(default_factory=list)
    suggested_urgency: str = "routine"

    @property
    def shown_alerts(self) -> list[Alert]:
        return [a for a in self.alerts if a.shown]


def build_facts(
    pack: Pack,
    *,
    patient_age: int | None,
    patient_sex: str | None,
    answers: dict[str, Any],
    probabilities: dict[str, float] | None,
    suspected: list[str] | None,
) -> dict[str, Any]:
    facts: dict[str, Any] = {f"exam.{k}": v for k, v in answers.items()}
    facts["patient.age"] = patient_age
    facts["patient.sex"] = patient_sex
    facts["patient.is_pediatric"] = (
        None if patient_age is None else patient_age < pack.pediatric_age_threshold
    )
    facts["suspected"] = list(suspected or [])
    for cid, p in (probabilities or {}).items():
        facts[f"model.{cid}"] = p
    return facts


def _model_conditions(e: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("all", "any"):
        for sub in e.get(key, []):
            out |= _model_conditions(sub)
    if "not" in e:
        out |= _model_conditions(e["not"])
    fact = e.get("fact", "")
    if isinstance(fact, str) and fact.startswith("model."):
        out.add(fact.removeprefix("model."))
    return out


def run_triage(
    pack: Pack,
    facts: dict[str, Any],
    probabilities: dict[str, float] | None,
    condition_states: dict[str, str] | None,
) -> TriageResult:
    assert pack.ruleset
    states = condition_states or {}
    result = TriageResult()

    for rule in pack.ruleset.red_flags:
        if not expr.evaluate(rule.when, facts):
            continue
        shown = True
        if rule.show_policy == "follow_model_state":
            shown = all(states.get(c) == "visible" for c in _model_conditions(rule.when))
        result.alerts.append(Alert(rule.id, rule.severity, dict(rule.message), "rules", shown, rule.referral))

    # Emergency-group conditions above threshold. Shown only when the condition is visible;
    # otherwise logged so we can measure what the model would have caught.
    threshold = pack.ruleset.emergency_model_threshold
    for c in pack.conditions:
        p = (probabilities or {}).get(c.id)
        if c.emergency and p is not None and p >= threshold:
            result.alerts.append(
                Alert(
                    rule_id="emergency_model",
                    subject=c.id,
                    severity="urgent",
                    message={
                        "en": f"AI flags a possible emergency: {c.name.get('en', c.id)}.",
                        "fil": f"Posibleng emergency ayon sa AI: {c.name.get('fil', c.name.get('en', c.id))}.",
                    },
                    source="model",
                    shown=states.get(c.id) == "visible",
                )
            )

    urgencies = [a.severity for a in result.shown_alerts]
    urgencies += [r.urgency for r in pack.ruleset.urgency_rules if expr.evaluate(r.when, facts)]
    result.suggested_urgency = max(urgencies, key=URGENCY_ORDER.__getitem__, default="routine")
    return result


def condition_urgency(pack: Pack, condition_id: str, is_pediatric: bool | None) -> str | None:
    c = pack.condition(condition_id)
    if c is None:
        return None
    if is_pediatric and c.pediatric_urgency:
        return c.pediatric_urgency
    return c.default_urgency


def max_urgency(*values: str | None) -> str:
    present = [v for v in values if v]
    return max(present, key=URGENCY_ORDER.__getitem__, default="routine")
