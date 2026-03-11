from __future__ import annotations

from enum import Enum


def normalize_extension_type_token(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        raise TypeError(f"{context} must be a string")
    normalized = value.strip().lower()
    if normalized == "industrial":
        return "Industrial"
    if normalized in {
        "financialservices",
        "financial_services",
        "financial services",
        "financial",
    }:
        return "FinancialServices"
    if normalized in {"realestate", "real_estate", "real estate"}:
        return "RealEstate"
    if normalized == "general":
        return None
    raise TypeError(f"{context} has unsupported value: {value!r}")
