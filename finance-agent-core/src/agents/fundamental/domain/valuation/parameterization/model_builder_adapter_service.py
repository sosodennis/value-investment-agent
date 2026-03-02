from __future__ import annotations

from collections.abc import Callable, Mapping

from ..report_contract import FinancialReport
from .contracts import (
    ModelParamBuilder,
    ParamBuilderPayload,
    ParamBuildResult,
)
from .model_builders.context import BuilderContext

LatestOnlyModelBuilder = Callable[
    [str | None, FinancialReport, Mapping[str, object] | None],
    ParamBuildResult,
]
ContextProvider = Callable[[], BuilderContext]
AssembleResultOp = Callable[
    [ParamBuilderPayload, FinancialReport, Mapping[str, object] | None],
    ParamBuildResult,
]
PayloadBuilderOp = Callable[
    [
        BuilderContext,
        str | None,
        FinancialReport,
        list[FinancialReport],
        Mapping[str, object] | None,
    ],
    ParamBuilderPayload,
]
LatestOnlyPayloadBuilderOp = Callable[
    [
        BuilderContext,
        str | None,
        FinancialReport,
        Mapping[str, object] | None,
    ],
    ParamBuilderPayload,
]


def build_multi_report_model_builder_from_payload(
    *,
    payload_builder: PayloadBuilderOp,
    context_provider: ContextProvider,
    assemble_result: AssembleResultOp,
) -> ModelParamBuilder:
    def _build(
        ticker: str | None,
        latest: FinancialReport,
        reports: list[FinancialReport],
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuildResult:
        payload = payload_builder(
            context_provider(),
            ticker,
            latest,
            reports,
            market_snapshot,
        )
        return assemble_result(payload, latest, market_snapshot)

    return _build


def build_latest_only_model_builder_from_payload(
    *,
    payload_builder: LatestOnlyPayloadBuilderOp,
    context_provider: ContextProvider,
    assemble_result: AssembleResultOp,
) -> LatestOnlyModelBuilder:
    def _build(
        ticker: str | None,
        latest: FinancialReport,
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuildResult:
        payload = payload_builder(
            context_provider(),
            ticker,
            latest,
            market_snapshot,
        )
        return assemble_result(payload, latest, market_snapshot)

    return _build


__all__ = [
    "AssembleResultOp",
    "ContextProvider",
    "LatestOnlyModelBuilder",
    "LatestOnlyPayloadBuilderOp",
    "PayloadBuilderOp",
    "build_latest_only_model_builder_from_payload",
    "build_multi_report_model_builder_from_payload",
]
