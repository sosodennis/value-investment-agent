from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, date, datetime

from src.shared.kernel.types import JSONObject


def to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def market_float(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> float | None:
    if market_snapshot is None:
        return None
    return to_float(market_snapshot.get(key))


def market_text(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> str | None:
    if market_snapshot is None:
        return None
    value = market_snapshot.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def market_text_list(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> list[str]:
    if market_snapshot is None:
        return []
    raw = market_snapshot.get(key)
    if not isinstance(raw, list | tuple):
        return []

    output: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            output.append(item)
    return output


def market_mapping(
    market_snapshot: Mapping[str, object] | None,
    key: str,
) -> Mapping[str, object] | None:
    if market_snapshot is None:
        return None
    raw = market_snapshot.get(key)
    if isinstance(raw, Mapping):
        return raw
    return None


def to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = to_bool(value)
    if parsed is None:
        return default
    return parsed


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    value = os.getenv(name)
    parsed = to_int(value)
    if parsed is None:
        parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized if normalized else default


def parse_iso_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass
    try:
        parsed_date = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)


def merge_metadata(base: JSONObject, extra: JSONObject) -> JSONObject:
    merged = dict(base)
    for key, value in extra.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            nested = dict(existing)
            nested.update(dict(value))
            merged[key] = nested
        else:
            merged[key] = value
    return merged
