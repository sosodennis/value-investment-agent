from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from ..report_contract import FinancialReport
from .contracts import ParamBuilderPayload
from .model_builders.bank import build_bank_payload
from .model_builders.context import BuilderContext
from .model_builders.dcf import build_dcf_growth_payload, build_dcf_standard_payload
from .model_builders.eva import build_eva_payload
from .model_builders.multiples import build_ev_ebitda_payload, build_ev_revenue_payload
from .model_builders.reit import build_reit_payload
from .model_builders.residual_income import build_residual_income_payload
from .model_builders.saas import build_saas_payload

DcfVariant = Literal["dcf_standard", "dcf_growth"]
EvMultipleVariant = Literal["ev_revenue", "ev_ebitda"]
MultiReportVariant = Literal["saas", "bank"]
SingleReportVariant = Literal["reit_ffo", "residual_income", "eva"]

_DCF_VARIANT_PAYLOAD_BUILDERS = {
    "dcf_standard": build_dcf_standard_payload,
    "dcf_growth": build_dcf_growth_payload,
}

_EV_MULTIPLE_PAYLOAD_BUILDERS = {
    "ev_revenue": build_ev_revenue_payload,
    "ev_ebitda": build_ev_ebitda_payload,
}

_MULTI_REPORT_PAYLOAD_BUILDERS = {
    "saas": build_saas_payload,
    "bank": build_bank_payload,
}

_MULTI_REPORT_DEPS_RESOLVERS = {
    "saas": BuilderContext.saas_deps,
    "bank": BuilderContext.bank_deps,
}

_SINGLE_REPORT_PAYLOAD_BUILDERS = {
    "reit_ffo": build_reit_payload,
    "residual_income": build_residual_income_payload,
    "eva": build_eva_payload,
}

_SINGLE_REPORT_DEPS_RESOLVERS = {
    "reit_ffo": BuilderContext.reit_deps,
    "residual_income": BuilderContext.residual_income_deps,
    "eva": BuilderContext.eva_deps,
}


def build_dcf_variant_payload(
    *,
    variant: DcfVariant,
    context: BuilderContext,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuilderPayload:
    payload_builder = _DCF_VARIANT_PAYLOAD_BUILDERS[variant]
    return payload_builder(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=context.dcf_variant_deps(),
    )


def build_ev_multiple_payload(
    *,
    variant: EvMultipleVariant,
    context: BuilderContext,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuilderPayload:
    payload_builder = _EV_MULTIPLE_PAYLOAD_BUILDERS[variant]
    return payload_builder(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=context.multiples_deps(),
    )


def build_multi_report_payload(
    *,
    variant: MultiReportVariant,
    context: BuilderContext,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuilderPayload:
    payload_builder = _MULTI_REPORT_PAYLOAD_BUILDERS[variant]
    deps_resolver = _MULTI_REPORT_DEPS_RESOLVERS[variant]
    return payload_builder(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=deps_resolver(context),
    )


def build_single_report_payload(
    *,
    variant: SingleReportVariant,
    context: BuilderContext,
    ticker: str | None,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuilderPayload:
    payload_builder = _SINGLE_REPORT_PAYLOAD_BUILDERS[variant]
    deps_resolver = _SINGLE_REPORT_DEPS_RESOLVERS[variant]
    return payload_builder(
        ticker=ticker,
        latest=latest,
        market_snapshot=market_snapshot,
        deps=deps_resolver(context),
    )
