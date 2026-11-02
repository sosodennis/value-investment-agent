from __future__ import annotations

from collections.abc import Sequence

from .contracts import ForwardSignalPayload


def serialize_forward_signals(
    forward_signals: Sequence[ForwardSignalPayload] | None,
) -> list[dict[str, object]] | None:
    if not forward_signals:
        return None
    return [signal.model_dump(exclude_none=True) for signal in forward_signals]


__all__ = ["serialize_forward_signals"]
