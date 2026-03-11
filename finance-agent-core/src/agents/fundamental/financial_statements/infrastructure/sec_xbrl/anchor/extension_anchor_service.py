from __future__ import annotations

from dataclasses import dataclass

from ..extractor import SearchConfig, SearchType

ANCHOR_RULE_NOT_FOUND = "ANCHOR_RULE_NOT_FOUND"

_DEFAULT_IS_STATEMENT_TOKENS = ["income", "operation", "earning"]
_DEFAULT_USD_UNITS = ["usd"]


@dataclass(frozen=True)
class AnchorResolution:
    field_key: str
    source: str | None
    configs: list[SearchConfig]
    unresolved_reason: str | None


class ExtensionAnchorService:
    def __init__(self) -> None:
        self._global_rules: dict[str, list[SearchConfig]] = {}
        self._industry_rules: dict[str, dict[str, list[SearchConfig]]] = {}
        self._issuer_rules: dict[str, dict[str, list[SearchConfig]]] = {}

    def register_global(
        self,
        field_key: str,
        configs: list[SearchConfig],
    ) -> None:
        self._global_rules[_normalize_token(field_key)] = list(configs)

    def register_industry(
        self,
        industry: str,
        field_key: str,
        configs: list[SearchConfig],
    ) -> None:
        normalized_industry = _normalize_token(industry)
        key = _normalize_token(field_key)
        bucket = self._industry_rules.setdefault(normalized_industry, {})
        bucket[key] = list(configs)

    def register_issuer(
        self,
        issuer: str,
        field_key: str,
        configs: list[SearchConfig],
    ) -> None:
        normalized_issuer = _normalize_issuer(issuer)
        key = _normalize_token(field_key)
        bucket = self._issuer_rules.setdefault(normalized_issuer, {})
        bucket[key] = list(configs)

    def resolve(
        self,
        *,
        field_key: str,
        industry: str | None = None,
        issuer: str | None = None,
    ) -> AnchorResolution:
        normalized_field_key = _normalize_token(field_key)
        if not normalized_field_key:
            return AnchorResolution(
                field_key=field_key,
                source=None,
                configs=[],
                unresolved_reason=ANCHOR_RULE_NOT_FOUND,
            )

        if issuer:
            issuer_bucket = self._issuer_rules.get(_normalize_issuer(issuer), {})
            issuer_configs = issuer_bucket.get(normalized_field_key)
            if issuer_configs:
                return AnchorResolution(
                    field_key=field_key,
                    source="issuer_anchor",
                    configs=list(issuer_configs),
                    unresolved_reason=None,
                )

        if industry:
            industry_bucket = self._industry_rules.get(_normalize_token(industry), {})
            industry_configs = industry_bucket.get(normalized_field_key)
            if industry_configs:
                return AnchorResolution(
                    field_key=field_key,
                    source="industry_anchor",
                    configs=list(industry_configs),
                    unresolved_reason=None,
                )

        global_configs = self._global_rules.get(normalized_field_key)
        if global_configs:
            return AnchorResolution(
                field_key=field_key,
                source="global_anchor",
                configs=list(global_configs),
                unresolved_reason=None,
            )
        return AnchorResolution(
            field_key=field_key,
            source=None,
            configs=[],
            unresolved_reason=ANCHOR_RULE_NOT_FOUND,
        )


def build_default_extension_anchor_service() -> ExtensionAnchorService:
    service = ExtensionAnchorService()

    # ---- Global anchor rules ----
    service.register_global(
        "income_before_tax",
        _income_statement_anchor_configs(
            [
                r"[a-z0-9_]+:(?:income|earnings).*(?:before|pre).*(?:tax|taxes)",
                r"[a-z0-9_]+:(?:pretax|pre_tax|pretaxincome).*",
            ]
        ),
    )

    # ---- Industry anchor rules ----
    service.register_industry(
        "Financial Services",
        "income_before_tax",
        _income_statement_anchor_configs(
            [
                r"[a-z0-9_]+:(?:income|earnings).*(?:before|pre).*(?:tax|taxes)",
            ]
        ),
    )

    # ---- Issuer anchor rules ----
    service.register_issuer(
        "AMZN",
        "income_before_tax",
        _income_statement_anchor_configs(
            [
                "amzn:IncomeBeforeIncomeTaxes",
                "amzn:IncomeBeforeTax",
            ]
        ),
    )
    return service


def _income_statement_anchor_configs(patterns: list[str]) -> list[SearchConfig]:
    return [
        SearchType.CONSOLIDATED(
            pattern,
            statement_types=_DEFAULT_IS_STATEMENT_TOKENS,
            period_type="duration",
            unit_whitelist=_DEFAULT_USD_UNITS,
        )
        for pattern in patterns
    ]


def _normalize_token(value: str) -> str:
    return value.strip().lower()


def _normalize_issuer(value: str) -> str:
    return value.strip().upper()
