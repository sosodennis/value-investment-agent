from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .anchor.extension_anchor_service import (
    ANCHOR_RULE_NOT_FOUND,
    ExtensionAnchorService,
    build_default_extension_anchor_service,
)
from .extractor import SearchConfig

FIELD_MAPPING_NOT_FOUND = "FIELD_MAPPING_NOT_FOUND"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    configs: list[SearchConfig]


@dataclass(frozen=True)
class ResolvedFieldSpec:
    field_key: str
    spec: FieldSpec
    source: str  # "issuer_override" | "industry_override" | "base" | "anchor_only"
    industry: str | None = None
    issuer: str | None = None
    anchor_source: str | None = None
    anchor_rule_count: int = 0


@dataclass(frozen=True)
class MappingResolution:
    resolved: ResolvedFieldSpec | None
    unresolved_reason: str | None


USD_UNITS = ["usd"]
SHARES_UNITS = ["shares"]
PURE_UNITS = ["pure"]
RATIO_UNITS = ["pure", "number"]

BS_STATEMENT_TOKENS = ["balance", "financial position"]
IS_STATEMENT_TOKENS = ["income", "operation", "earning"]
CF_STATEMENT_TOKENS = ["cash"]


class XbrlMappingRegistry:
    def __init__(
        self,
        *,
        anchor_service: ExtensionAnchorService | None = None,
    ) -> None:
        self._fields: dict[str, FieldSpec] = {}
        self._industry_overrides: dict[str, dict[str, FieldSpec]] = {}
        self._issuer_overrides: dict[str, dict[str, FieldSpec]] = {}
        self._anchor_service = (
            anchor_service or build_default_extension_anchor_service()
        )

    def register(self, field_key: str, spec: FieldSpec) -> None:
        self._fields[field_key] = spec

    def register_override(self, industry: str, field_key: str, spec: FieldSpec) -> None:
        self.register_industry_override(industry, field_key, spec)

    def register_industry_override(
        self, industry: str, field_key: str, spec: FieldSpec
    ) -> None:
        if industry not in self._industry_overrides:
            self._industry_overrides[industry] = {}
        self._industry_overrides[industry][field_key] = spec

    def register_issuer_override(
        self, issuer: str, field_key: str, spec: FieldSpec
    ) -> None:
        normalized_issuer = self._normalize_issuer(issuer)
        if normalized_issuer not in self._issuer_overrides:
            self._issuer_overrides[normalized_issuer] = {}
        self._issuer_overrides[normalized_issuer][field_key] = spec

    @staticmethod
    def _normalize_issuer(issuer: str) -> str:
        return issuer.strip().upper()

    def resolve(
        self,
        field_key: str,
        *,
        industry: str | None = None,
        issuer: str | None = None,
    ) -> ResolvedFieldSpec | None:
        return self.resolve_with_reason(
            field_key,
            industry=industry,
            issuer=issuer,
        ).resolved

    def resolve_with_reason(
        self,
        field_key: str,
        *,
        industry: str | None = None,
        issuer: str | None = None,
    ) -> MappingResolution:
        base_resolution = self._resolve_base(
            field_key=field_key,
            industry=industry,
            issuer=issuer,
        )
        anchor_resolution = self._anchor_service.resolve(
            field_key=field_key,
            industry=industry,
            issuer=issuer,
        )
        anchor_configs = anchor_resolution.configs
        anchor_source = anchor_resolution.source

        if base_resolution is None and not anchor_configs:
            unresolved_reason = (
                FIELD_MAPPING_NOT_FOUND
                if anchor_resolution.unresolved_reason == ANCHOR_RULE_NOT_FOUND
                else anchor_resolution.unresolved_reason
            )
            return MappingResolution(
                resolved=None,
                unresolved_reason=unresolved_reason,
            )

        if base_resolution is None:
            spec = FieldSpec(
                name=_default_field_name(field_key),
                configs=list(anchor_configs),
            )
            return MappingResolution(
                resolved=ResolvedFieldSpec(
                    field_key=field_key,
                    spec=spec,
                    source="anchor_only",
                    industry=industry,
                    issuer=self._normalize_issuer(issuer) if issuer else None,
                    anchor_source=anchor_source,
                    anchor_rule_count=len(anchor_configs),
                ),
                unresolved_reason=None,
            )

        if not anchor_configs:
            return MappingResolution(resolved=base_resolution, unresolved_reason=None)

        combined = _dedupe_configs([*anchor_configs, *base_resolution.spec.configs])
        return MappingResolution(
            resolved=ResolvedFieldSpec(
                field_key=base_resolution.field_key,
                spec=FieldSpec(name=base_resolution.spec.name, configs=combined),
                source=base_resolution.source,
                industry=base_resolution.industry,
                issuer=base_resolution.issuer,
                anchor_source=anchor_source,
                anchor_rule_count=len(anchor_configs),
            ),
            unresolved_reason=None,
        )

    def _resolve_base(
        self,
        *,
        field_key: str,
        industry: str | None,
        issuer: str | None,
    ) -> ResolvedFieldSpec | None:
        if issuer:
            normalized_issuer = self._normalize_issuer(issuer)
            issuer_overrides = self._issuer_overrides.get(normalized_issuer, {})
            if field_key in issuer_overrides:
                return ResolvedFieldSpec(
                    field_key=field_key,
                    spec=issuer_overrides[field_key],
                    source="issuer_override",
                    industry=industry,
                    issuer=normalized_issuer,
                )

        if industry:
            industry_overrides = self._industry_overrides.get(industry, {})
            if field_key in industry_overrides:
                return ResolvedFieldSpec(
                    field_key=field_key,
                    spec=industry_overrides[field_key],
                    source="industry_override",
                    industry=industry,
                    issuer=self._normalize_issuer(issuer) if issuer else None,
                )

        base_spec = self._fields.get(field_key)
        if base_spec is None:
            return None
        return ResolvedFieldSpec(
            field_key=field_key,
            spec=base_spec,
            source="base",
            industry=industry,
            issuer=self._normalize_issuer(issuer) if issuer else None,
        )

    def get(self, field_key: str, industry: str | None = None) -> FieldSpec | None:
        resolved = self.resolve(field_key, industry=industry)
        if not resolved:
            return None
        return resolved.spec

    def list_fields(self) -> list[str]:
        return sorted(self._fields.keys())


def build_default_mapping_registry() -> XbrlMappingRegistry:
    registry = XbrlMappingRegistry()
    # Delayed import avoids circular import during registry assembly.
    from .mappings import register_all_mappings

    register_all_mappings(registry)
    return registry


@lru_cache(maxsize=1)
def get_mapping_registry() -> XbrlMappingRegistry:
    return build_default_mapping_registry()


def _default_field_name(field_key: str) -> str:
    words = [token for token in field_key.replace("-", "_").split("_") if token]
    if not words:
        return field_key
    return " ".join(token.capitalize() for token in words)


def _dedupe_configs(configs: list[SearchConfig]) -> list[SearchConfig]:
    deduped: list[SearchConfig] = []
    seen: set[tuple[object, ...]] = set()
    for config in configs:
        key = _search_config_key(config)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(config)
    return deduped


def _search_config_key(config: SearchConfig) -> tuple[object, ...]:
    return (
        config.concept_regex,
        config.type_name,
        config.dimension_regex,
        tuple(config.statement_types or []),
        config.period_type,
        tuple(config.unit_whitelist or []),
        tuple(config.unit_blacklist or []),
        config.respect_anchor_date,
    )
