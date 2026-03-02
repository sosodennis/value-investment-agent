from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchTask:
    time_param: str
    query: str
    limit: int
    tag: str
    fallbacks: tuple[str, ...] = field(default_factory=tuple)
