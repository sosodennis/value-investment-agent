from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManagedProviderKey:
    id: str
    label: str
    suffix: str
    fingerprint: str
    created_at: str | None
    status: str = "untested"
    last_tested_at: str | None = None
    failure_count: int = 0
    cooldown_until: str | None = None
    last_error: str | None = None
    last_used_at: str | None = None
    replacement_retire_at: str | None = None


@dataclass(frozen=True)
class ProviderKeyHealth:
    status: str
    failure_count: int
    cooldown_until: str | None
    last_error: str | None
    last_used_at: str | None


@dataclass(frozen=True)
class OpenRouterModel:
    id: str
    name: str
    description: str | None
    context_length: int | None
