from __future__ import annotations

from collections.abc import Mapping

from ..report_contract import FinancialReport
from .contracts import ParamBuilderPayload, ParamBuildResult
from .metadata_service import (
    build_result_metadata as _build_result_metadata,
)
from .series_service import dedupe_missing as _dedupe_missing


def build_param_result(
    payload: ParamBuilderPayload,
    latest: FinancialReport,
    market_snapshot: Mapping[str, object] | None,
) -> ParamBuildResult:
    return ParamBuildResult(
        params=payload.params,
        trace_inputs=payload.trace_inputs,
        missing=_dedupe_missing(payload.missing),
        assumptions=payload.assumptions,
        metadata=_build_result_metadata(
            latest=latest,
            market_snapshot=market_snapshot,
            shares_source=payload.shares_source,
            terminal_growth_path=(
                payload.terminal_growth_path
                if isinstance(getattr(payload, "terminal_growth_path", None), Mapping)
                else None
            ),
            shares_path=(
                payload.shares_path
                if isinstance(getattr(payload, "shares_path", None), Mapping)
                else None
            ),
        ),
    )
