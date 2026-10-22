from __future__ import annotations

from hashlib import sha256


def key_suffix(value: str) -> str:
    return value[-4:] if len(value) >= 4 else "****"


def key_fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]


def validate_model_id(value: str) -> str:
    """Keep deployment identifiers opaque while rejecting empty path values."""
    if not value.strip() or len(value) > 200:
        raise ValueError("invalid managed key id")
    return value
