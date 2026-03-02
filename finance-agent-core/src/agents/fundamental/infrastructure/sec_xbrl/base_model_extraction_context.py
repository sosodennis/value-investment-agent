from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .extractor import SearchConfig, SearchType


class ResolveConfigsFn(Protocol):
    def __call__(
        self, *, field_key: str, industry: str | None, issuer: str | None
    ) -> list[SearchConfig]: ...


@dataclass(slots=True)
class BaseModelExtractionContext:
    industry: str
    issuer_ticker: str
    resolve_configs_fn: ResolveConfigsFn

    def build_config(
        self,
        regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
    ) -> SearchConfig:
        return SearchType.CONSOLIDATED(
            regex,
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
        )

    def resolve_configs(self, field_key: str) -> list[SearchConfig]:
        return self.resolve_configs_fn(
            field_key=field_key,
            industry=self.industry,
            issuer=self.issuer_ticker,
        )
