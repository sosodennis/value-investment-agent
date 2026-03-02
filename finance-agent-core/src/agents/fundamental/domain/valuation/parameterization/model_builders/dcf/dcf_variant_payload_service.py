from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ....report_contract import FinancialReport
from ..saas import SaasBuilderDeps, SaasBuildPayload, build_saas_payload


@dataclass(frozen=True)
class DCFVariantBuilderDeps:
    saas_deps: SaasBuilderDeps


def build_dcf_variant_payload(
    *,
    payload: SaasBuildPayload,
    model_variant: str,
) -> SaasBuildPayload:
    params = dict(payload.params)
    params["model_variant"] = model_variant

    assumptions = list(payload.assumptions)
    assumptions.append(
        f"model_variant={model_variant} routed via dedicated param builder"
    )

    return SaasBuildPayload(
        params=params,
        trace_inputs=payload.trace_inputs,
        missing=payload.missing,
        assumptions=assumptions,
        shares_source=payload.shares_source,
    )


def build_dcf_variant_model_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    saas_deps: SaasBuilderDeps,
    model_variant: str,
) -> SaasBuildPayload:
    payload = build_saas_payload(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=saas_deps,
    )
    return build_dcf_variant_payload(
        payload=payload,
        model_variant=model_variant,
    )
