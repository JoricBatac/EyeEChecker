"""Imports every model so Base.metadata is complete."""

from app.modules.assessment.models import Assessment
from app.modules.assist.models import AccessCode, AssistScore
from app.modules.audit.models import AuditLog
from app.modules.encounters.models import AIResult, Encounter, ExamAnswers, Feedback, Photo, RedFlagAlert
from app.modules.orgs.models import Organization, OrgPack, Site, User
from app.modules.packs.models import ConditionState
from app.modules.patients.models import Consent, Patient
from app.modules.referrals.models import Referral
from app.modules.reports.models import Report
from app.modules.review.models import ReviewNote

__all__ = [
    "AIResult",
    "AccessCode",
    "AssistScore",
    "Assessment",
    "AuditLog",
    "ConditionState",
    "Consent",
    "Encounter",
    "ExamAnswers",
    "Feedback",
    "OrgPack",
    "Organization",
    "Patient",
    "Photo",
    "RedFlagAlert",
    "Referral",
    "Report",
    "ReviewNote",
    "Site",
    "User",
]
