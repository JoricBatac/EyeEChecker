from enum import StrEnum


class Role(StrEnum):
    clinician = "clinician"
    staff = "staff"
    org_admin = "org_admin"
    internal_reviewer = "internal_reviewer"
    internal_admin = "internal_admin"


class Profession(StrEnum):
    optometrist = "optometrist"
    physician = "physician"
    ophthalmologist = "ophthalmologist"
    nurse = "nurse"
    other = "other"


CLINIC_ROLES = {Role.clinician, Role.staff, Role.org_admin}
INTERNAL_ROLES = {Role.internal_reviewer, Role.internal_admin}
MFA_ROLES = {Role.org_admin, Role.internal_admin, Role.internal_reviewer}
