from __future__ import annotations

import re
import unicodedata


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


def normalize_display_name(value: str) -> str:
    display_name = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    if not display_name:
        raise AuthPolicyError("display name is required")
    if len(display_name) > 80:
        raise AuthPolicyError("display name is too long")
    if len(display_name.casefold()) > 80:
        raise AuthPolicyError("display name is too long")
    if any(
        unicodedata.category(character).startswith("C") for character in display_name
    ):
        raise AuthPolicyError("display name contains an invalid character")
    return display_name


def normalize_directory_query(value: str) -> str:
    query = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    if len(query) > 80:
        raise AuthPolicyError("directory query is too long")
    return query.casefold()


def session_is_active(*, expires_at, revoked_at, now) -> bool:
    return revoked_at is None and expires_at > now
