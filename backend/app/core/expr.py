"""Small JSON expression language used by pack rulesets, exam forms and capture protocols.

    {"all": [...]}, {"any": [...]}, {"not": {...}}
    {"fact": "exam.pain_severity", "op": "in", "value": ["moderate", "severe"]}

Facts are a flat dict ("exam.<field>", "patient.age", "model.<condition_id>", "suspected").
A missing fact makes every comparison false, so incomplete data never fires or suppresses a rule by accident;
rules that should fire on missing data must say so with "missing".
"""

from __future__ import annotations

from typing import Any

_MISSING = object()

OPS = {"eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "contains", "contains_any", "exists", "missing"}


def evaluate(expr: dict[str, Any], facts: dict[str, Any]) -> bool:
    if "all" in expr:
        return all(evaluate(e, facts) for e in expr["all"])
    if "any" in expr:
        return any(evaluate(e, facts) for e in expr["any"])
    if "not" in expr:
        return not evaluate(expr["not"], facts)

    op = expr["op"]
    actual = facts.get(expr["fact"], _MISSING)
    if op == "exists":
        return actual is not _MISSING and actual is not None
    if op == "missing":
        return actual is _MISSING or actual is None
    if actual is _MISSING or actual is None:
        return False
    expected: Any = expr.get("value")
    try:
        match op:
            case "eq":
                return actual == expected
            case "ne":
                return actual != expected
            case "in":
                return actual in expected
            case "not_in":
                return actual not in expected
            case "lt":
                return actual < expected
            case "lte":
                return actual <= expected
            case "gt":
                return actual > expected
            case "gte":
                return actual >= expected
            case "contains":
                return isinstance(actual, (list, tuple, set)) and expected in actual
            case "contains_any":
                return isinstance(actual, (list, tuple, set)) and any(v in actual for v in expected)
    except TypeError:
        return False
    raise ValueError(f"unknown operator {op!r}")


def validate(expr: Any, known_facts: set[str] | None = None, path: str = "") -> list[str]:
    """Return a list of problems in an expression (used by the pack loader)."""
    if not isinstance(expr, dict):
        return [f"{path}: expression must be an object"]
    for combinator in ("all", "any"):
        if combinator in expr:
            items = expr[combinator]
            if not isinstance(items, list) or not items:
                return [f"{path}.{combinator}: must be a non-empty list"]
            return [
                p for i, e in enumerate(items) for p in validate(e, known_facts, f"{path}.{combinator}[{i}]")
            ]
    if "not" in expr:
        return validate(expr["not"], known_facts, f"{path}.not")
    problems = []
    if expr.get("op") not in OPS:
        problems.append(f"{path}: unknown op {expr.get('op')!r}")
    fact = expr.get("fact")
    if not isinstance(fact, str):
        problems.append(f"{path}: missing fact")
    elif known_facts is not None and not _fact_known(fact, known_facts):
        problems.append(f"{path}: unknown fact {fact!r}")
    return problems


def _fact_known(fact: str, known: set[str]) -> bool:
    return fact in known or any(k.endswith(".*") and fact.startswith(k[:-1]) for k in known)
