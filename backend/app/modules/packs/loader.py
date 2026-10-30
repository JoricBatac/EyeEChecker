"""Specialty pack loading and validation (PRD 5).

The core platform knows nothing about any specialty; everything specific comes from packs/<id>/.
A pack that fails validation stops the app from starting.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from app.core import expr
from app.core.config import get_settings

Localized = dict[str, str]
Urgency = Literal["routine", "soon", "urgent"]
URGENCY_ORDER = {"routine": 0, "soon": 1, "urgent": 2}
CONDITION_STATES = ("off", "shadow", "reveal_after", "visible")


class Condition(BaseModel):
    id: str
    name: Localized
    default_urgency: Urgency | None = None
    emergency: bool = False
    classifiable: bool = True
    always_refer: bool = False
    referral_reason: Localized | None = None
    required_exam_fields_by_side: dict[Literal["right", "left"], list[str]] = Field(default_factory=dict)
    pediatric_urgency: Urgency | None = None
    zero_shot_prompts: list[str] = Field(default_factory=list)
    # Plain-language "why" content shown next to AI suggestions.
    visual_features: Localized | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Evidence(BaseModel):
    """An exam finding that supports or argues against a condition (explanation only, never scoring)."""

    direction: Literal["supports", "against"]
    text: Localized
    when: dict[str, Any]


Condition.model_rebuild()


class Option(BaseModel):
    value: str
    label: Localized


class FormField(BaseModel):
    id: str
    type: Literal["single", "multi", "number", "text", "boolean", "visual_acuity"]
    label: Localized
    required: bool = False
    required_if: dict[str, Any] | None = None
    show_if: dict[str, Any] | None = None
    options: list[Option] = Field(default_factory=list)
    free_text: bool = False
    min: float | None = None
    max: float | None = None


class ExamForm(BaseModel):
    version: int
    fields: list[FormField]


class CaptureView(BaseModel):
    id: str
    label: Localized
    required: bool = False
    overlay: str | None = None
    flash: bool = False
    instructions: Localized
    quality_overrides: dict[str, float] = Field(default_factory=dict)


class ConditionalViews(BaseModel):
    when: dict[str, Any]
    require: list[str]


class CaptureProtocol(BaseModel):
    views: list[CaptureView]
    conditional_views: list[ConditionalViews] = Field(default_factory=list)
    quality: dict[str, float]
    retake_tips: dict[str, Localized]
    # Optional lighting tag on a single uploaded photo -> which view's quality thresholds apply.
    lighting_views: dict[str, str] = Field(default_factory=dict)
    lighting_labels: dict[str, Localized] = Field(default_factory=dict)


class RedFlagRule(BaseModel):
    id: str
    severity: Urgency
    show_policy: Literal["always", "follow_model_state"] = "always"
    referral: bool = False
    message: Localized
    when: dict[str, Any]


class UrgencyRule(BaseModel):
    id: str
    urgency: Urgency
    when: dict[str, Any]


class Ruleset(BaseModel):
    version: str
    emergency_model_threshold: float = 0.3
    red_flags: list[RedFlagRule]
    urgency_rules: list[UrgencyRule] = Field(default_factory=list)


class ManagementOption(BaseModel):
    id: str
    text: Localized
    professions: list[str]
    referral: bool = False


class ModelRef(BaseModel):
    kind: Literal["none", "stub", "zero_shot", "onnx"] = "none"
    version: str = "none"
    onnx_dir: str | None = None


class Pack(BaseModel):
    id: str
    version: str
    name: Localized
    placeholder: bool = False
    pediatric_age_threshold: int = 18
    default_condition_state: Literal["off", "shadow", "reveal_after", "visible"] = "off"
    likelihood_bands: dict[str, float] = Field(default_factory=lambda: {"high": 0.6, "moderate": 0.3})
    model: ModelRef = Field(default_factory=ModelRef)
    root: Path | None = None

    conditions: list[Condition] = Field(default_factory=list)
    capture_protocol: CaptureProtocol | None = None
    exam_form: ExamForm | None = None
    ruleset: Ruleset | None = None
    management_common: list[ManagementOption] = Field(default_factory=list)
    management: dict[str, list[ManagementOption]] = Field(default_factory=dict)
    templates: dict[str, str] = Field(default_factory=dict)  # "<type>.<locale>" -> template source
    content: dict[str, dict[str, str]] = Field(default_factory=dict)  # locale -> condition_id -> text

    def condition(self, condition_id: str) -> Condition | None:
        return next((c for c in self.conditions if c.id == condition_id), None)

    @property
    def condition_ids(self) -> list[str]:
        return [c.id for c in self.conditions]

    @property
    def classifiable_ids(self) -> list[str]:
        return [c.id for c in self.conditions if c.classifiable]

    def field(self, field_id: str) -> FormField | None:
        if not self.exam_form:
            return None
        return next((f for f in self.exam_form.fields if f.id == field_id), None)

    def management_for(self, profession: str | None) -> dict[str, list[ManagementOption]]:
        """Management library filtered by scope of practice."""
        allowed = lambda o: profession is not None and profession in o.professions  # noqa: E731
        out = {cid: [o for o in opts if allowed(o)] for cid, opts in self.management.items()}
        out["common"] = [o for o in self.management_common if allowed(o)]
        return out

    def management_option(self, option_id: str, condition_ids: list[str]) -> ManagementOption | None:
        for cid in condition_ids:
            for o in self.management.get(cid, []):
                if o.id == option_id:
                    return o
        return next((o for o in self.management_common if o.id == option_id), None)

    def known_facts(self) -> set[str]:
        facts = {"patient.age", "patient.is_pediatric", "patient.sex", "suspected"}
        if self.exam_form:
            facts |= {f"exam.{f.id}" for f in self.exam_form.fields}
        facts |= {f"model.{cid}" for cid in self.classifiable_ids}
        return facts


class PackError(Exception):
    pass


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pack(root: Path) -> Pack:
    meta = _read_json(root / "pack.json")
    files = meta.pop("files", {})
    meta = {k: v for k, v in meta.items() if not k.startswith("_")}
    pack = Pack(**meta, root=root)
    if pack.placeholder:
        return pack

    pack.conditions = [Condition(**c) for c in _read_json(root / files["conditions"])["conditions"]]
    pack.capture_protocol = CaptureProtocol(**_read_json(root / files["capture_protocol"]))
    pack.exam_form = ExamForm(**_read_json(root / files["exam_form"]))
    pack.ruleset = Ruleset(
        **{k: v for k, v in _read_json(root / files["ruleset"]).items() if not k.startswith("_")}
    )

    lib = yaml.safe_load((root / files["management_library"]).read_text(encoding="utf-8")) or {}
    pack.management_common = [ManagementOption(**o) for o in lib.get("common", [])]
    pack.management = {
        cid: [ManagementOption(**o) for o in opts] for cid, opts in (lib.get("conditions") or {}).items()
    }

    for tpl in sorted((root / files["report_templates"]).glob("*.md.j2")):
        pack.templates[tpl.name.removesuffix(".md.j2")] = tpl.read_text(encoding="utf-8")

    content_dir = root / files["content"]
    for locale_dir in sorted(p for p in content_dir.iterdir() if p.is_dir()):
        data = _read_json(locale_dir / "conditions.json")
        pack.content[locale_dir.name] = {k: v for k, v in data.items() if not k.startswith("_")}

    problems = validate_pack(pack)
    if problems:
        raise PackError(f"pack {pack.id!r} is invalid:\n  - " + "\n  - ".join(problems))
    return pack


def validate_pack(pack: Pack) -> list[str]:
    problems: list[str] = []
    assert pack.exam_form and pack.ruleset and pack.capture_protocol

    ids = pack.condition_ids
    if len(ids) != len(set(ids)):
        problems.append("duplicate condition ids")
    field_ids = [f.id for f in pack.exam_form.fields]
    if len(field_ids) != len(set(field_ids)):
        problems.append("duplicate exam field ids")
    for c in pack.conditions:
        for side_fields in c.required_exam_fields_by_side.values():
            problems += [
                f"condition {c.id}: unknown exam field {f}" for f in side_fields if f not in field_ids
            ]
        if c.always_refer and not c.referral_reason:
            problems.append(f"condition {c.id}: always_refer needs referral_reason")
        if c.classifiable and pack.model.kind == "zero_shot" and not c.zero_shot_prompts:
            problems.append(f"condition {c.id}: zero-shot model needs zero_shot_prompts")
    for f in pack.exam_form.fields:
        if f.type in ("single", "multi") and not f.options:
            problems.append(f"field {f.id}: choice field has no options")
    facts = pack.known_facts()
    for f in pack.exam_form.fields:
        for key in ("required_if", "show_if"):
            if getattr(f, key):
                problems += expr.validate(getattr(f, key), facts, f"field {f.id}.{key}")
    for r in pack.ruleset.red_flags:
        problems += expr.validate(r.when, facts, f"red_flag {r.id}")
    for u in pack.ruleset.urgency_rules:
        problems += expr.validate(u.when, facts, f"urgency_rule {u.id}")
    view_ids = {v.id for v in pack.capture_protocol.views}
    for i, cv in enumerate(pack.capture_protocol.conditional_views):
        problems += expr.validate(cv.when, facts, f"conditional_views[{i}]")
        problems += [f"conditional_views[{i}]: unknown view {v}" for v in cv.require if v not in view_ids]
    for c in pack.conditions:
        for i, ev in enumerate(c.evidence):
            problems += expr.validate(ev.when, facts, f"condition {c.id}.evidence[{i}]")
    problems += [
        f"lighting_views: unknown view {v}"
        for v in pack.capture_protocol.lighting_views.values()
        if v not in view_ids
    ]
    for cid in pack.management:
        if cid not in ids:
            problems.append(f"management library: unknown condition {cid}")
    if "exam_note.en" not in pack.templates:
        problems.append("missing report template exam_note.en")
    for locale, texts in pack.content.items():
        problems += [f"content/{locale}: unknown condition {k}" for k in texts if k not in ids]
    return problems


def load_all(packs_dir: Path) -> dict[str, Pack]:
    packs: dict[str, Pack] = {}
    for root in sorted(p for p in packs_dir.iterdir() if (p / "pack.json").exists()):
        pack = load_pack(root)
        if pack.id in packs:
            raise PackError(f"duplicate pack id {pack.id}")
        packs[pack.id] = pack
    return packs


@lru_cache
def get_packs() -> dict[str, Pack]:
    return load_all(get_settings().packs_dir)


def get_pack(pack_id: str) -> Pack | None:
    return get_packs().get(pack_id)


_VA_RE = re.compile(r"^(\d{1,2}/\d{1,3}|CF|HM|LP|NLP)$")


def validate_answers(pack: Pack, answers: dict[str, Any]) -> list[str]:
    """Type-check exam answers against the pack's form. Partial answers are allowed."""
    assert pack.exam_form
    errors = []
    for key, value in answers.items():
        f = pack.field(key)
        if f is None:
            errors.append(f"{key}: unknown field")
            continue
        if value is None:
            continue
        values = [o.value for o in f.options]
        ok = True
        match f.type:
            case "single":
                ok = value in values
            case "multi":
                ok = isinstance(value, list) and all(v in values for v in value)
            case "boolean":
                ok = isinstance(value, bool)
            case "number":
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                ok = ok and (f.min is None or value >= f.min) and (f.max is None or value <= f.max)
            case "text":
                ok = isinstance(value, str) and len(value) <= 2000
            case "visual_acuity":
                ok = isinstance(value, str) and bool(_VA_RE.match(value.strip().upper()))
        if not ok:
            errors.append(f"{key}: invalid value")
    return errors


def missing_required(pack: Pack, facts: dict[str, Any]) -> list[str]:
    assert pack.exam_form
    missing = []
    for f in pack.exam_form.fields:
        if f.show_if and not expr.evaluate(f.show_if, facts):
            continue
        required = f.required or (f.required_if is not None and expr.evaluate(f.required_if, facts))
        value = facts.get(f"exam.{f.id}")
        if required and (value is None or value == "" or value == []):
            missing.append(f.id)
    return missing
