from __future__ import annotations

from collections.abc import Mapping

from ....report_contract import FinancialReport
from ..saas import SaasBuildPayload
from .dcf_variant_payload_service import (
    DCFVariantBuilderDeps,
    build_dcf_variant_model_payload,
)


def build_dcf_standard_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    deps: DCFVariantBuilderDeps,
) -> SaasBuildPayload:
    return build_dcf_variant_model_payload(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        saas_deps=deps.saas_deps,
        model_variant="dcf_standard",
    )
