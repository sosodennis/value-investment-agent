from __future__ import annotations

from dataclasses import dataclass

from .extractor import SearchConfig


@dataclass(frozen=True)
class FieldSpec:
    name: str
    configs: list[SearchConfig]


@dataclass(frozen=True)
class ResolvedFieldSpec:
    field_key: str
    spec: FieldSpec
    source: str  # "issuer_override" | "industry_override" | "base"
    industry: str | None = None
    issuer: str | None = None


USD_UNITS = ["usd"]
SHARES_UNITS = ["shares"]
PURE_UNITS = ["pure"]

BS_STATEMENT_TOKENS = ["balance", "financial position"]
IS_STATEMENT_TOKENS = ["income", "operation", "earning"]
CF_STATEMENT_TOKENS = ["cash"]


class XbrlMappingRegistry:
    def __init__(self) -> None:
        self._fields: dict[str, FieldSpec] = {}
        self._industry_overrides: dict[str, dict[str, FieldSpec]] = {}
        self._issuer_overrides: dict[str, dict[str, FieldSpec]] = {}

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


REGISTRY = XbrlMappingRegistry()


def _register_default_mappings() -> None:
    # Delayed import avoids circular import during module bootstrap.
    from .mappings import register_all_mappings

    register_all_mappings(REGISTRY)


_register_default_mappings()
