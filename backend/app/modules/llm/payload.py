"""The only data the report-polishing LLM may receive (PRD 10.4).

No photos, image URLs, patient or clinic identifiers, or free text typed by the clinician.
`extra="forbid"` everywhere means adding a field is a deliberate schema change caught by tests.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Placeholders the LLM must keep; real values are substituted after generation.
PLACEHOLDERS = ("{{PATIENT_NAME}}", "{{DATE}}", "{{CLINICIAN_NAME}}", "{{CLINIC_NAME}}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PayloadCondition(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(max_length=120)
    side: Literal["right", "left", "both"] | None = None


class PayloadFinding(_Strict):
    label: str = Field(max_length=120)
    value: str = Field(max_length=120)


class AllowlistedPayload(_Strict):
    report_type: Literal["exam_note", "referral_letter", "patient_handout"]
    locale: Literal["en", "fil"]
    age_band: Literal["child", "adult", "unknown"]
    conditions: list[PayloadCondition]
    urgency: Literal["routine", "soon", "urgent"]
    findings: list[PayloadFinding]
    plan: list[str]
    referral_reasons: list[str]
    red_flags: list[str]
