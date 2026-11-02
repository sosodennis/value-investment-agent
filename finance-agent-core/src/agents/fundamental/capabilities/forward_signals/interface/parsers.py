from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from .contracts import ForwardSignalPayload


def parse_forward_signals(
    value: object, *, context: str
) -> list[ForwardSignalPayload] | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple):
        raise TypeError(f"{context} must be a list")

    parsed: list[ForwardSignalPayload] = []
    for item in value:
        if isinstance(item, ForwardSignalPayload):
            parsed.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        try:
            parsed.append(ForwardSignalPayload.model_validate(item))
        except ValidationError:
            continue
    return parsed or None


__all__ = ["parse_forward_signals"]
