from __future__ import annotations

import re


class AuthPolicyError(ValueError):
    """Raised when an authentication domain value violates policy."""


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not _EMAIL_PATTERN.fullmatch(email):
        raise AuthPolicyError("enter a valid email address")
    return email


def validate_password(value: str) -> str:
    if len(value) < 8:
        raise AuthPolicyError("password must be at least 8 characters")
    if len(value) > 200:
        raise AuthPolicyError("password is too long")
    return value


def session_is_active(*, expires_at, revoked_at, now) -> bool:
    return revoked_at is None and expires_at > now
