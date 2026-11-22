"""Canonical fundamental-json-v1 serialization and digest helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

_JSON_SCALAR_TYPES = frozenset((str, int, float, bool, type(None)))


def _canonical(value: Any) -> Any:
    if type(value) in _JSON_SCALAR_TYPES:
        return value
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def canonical_bytes(value: Any) -> bytes:
    """Return the UTF-8, sorted, compact fundamental-json-v1 representation."""
    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_array_parts(items: Iterable[bytes]) -> Iterator[bytes]:
    yield b"["
    for index, item in enumerate(items):
        if index:
            yield b","
        yield item
    yield b"]"


def canonical_object_parts(
    fields: Mapping[str, Any], embedded: Mapping[str, Iterable[bytes]]
) -> Iterator[bytes]:
    """Compose owner-produced canonical JSON values without expanding them."""
    if fields.keys() & embedded.keys():
        raise ValueError("canonical object fields must be distinct")
    yield b"{"
    for index, key in enumerate(sorted((*fields, *embedded))):
        if index:
            yield b","
        yield canonical_bytes(key)
        yield b":"
        if key in embedded:
            yield from embedded[key]
        else:
            yield canonical_bytes(fields[key])
    yield b"}"


def sha256_parts(parts: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def is_digest(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
