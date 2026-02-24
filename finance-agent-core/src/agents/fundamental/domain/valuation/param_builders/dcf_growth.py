from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..report_contract import FinancialReport
from .saas import SaasBuilderDeps, SaasBuildPayload, build_saas_payload


@dataclass(frozen=True)
class DCFGrowthBuilderDeps:
    saas_deps: SaasBuilderDeps


def build_dcf_growth_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: DCFGrowthBuilderDeps,
) -> SaasBuildPayload:
    payload = build_saas_payload(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=deps.saas_deps,
    )

    params = dict(payload.params)
    params["model_variant"] = "dcf_growth"

    assumptions = list(payload.assumptions)
    assumptions.append("model_variant=dcf_growth routed via dedicated param builder")

    return SaasBuildPayload(
        params=params,
        trace_inputs=payload.trace_inputs,
        missing=payload.missing,
        assumptions=assumptions,
        shares_source=payload.shares_source,
    )
