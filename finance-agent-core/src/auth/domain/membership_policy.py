from __future__ import annotations

from src.auth.domain.entities import MembershipStatus
from src.auth.domain.policies import AuthPolicyError

ALLOWED_MEMBERSHIP_STATUS_TRANSITIONS: dict[
    MembershipStatus, frozenset[MembershipStatus]
] = {
    MembershipStatus.PENDING: frozenset(),
    MembershipStatus.ACTIVE: frozenset(
        {MembershipStatus.SUSPENDED, MembershipStatus.REMOVED}
    ),
    MembershipStatus.SUSPENDED: frozenset(
        {MembershipStatus.ACTIVE, MembershipStatus.REMOVED}
    ),
    MembershipStatus.REMOVED: frozenset(),
}


def is_allowed_membership_status_transition(
    *, current: MembershipStatus, requested: MembershipStatus
) -> bool:
    if current is requested:
        return True
    return requested in ALLOWED_MEMBERSHIP_STATUS_TRANSITIONS[current]


def normalize_organization_name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > 120 or any(ord(char) < 32 for char in name):
        raise AuthPolicyError("organization name must be 1-120 printable characters")
    return name
