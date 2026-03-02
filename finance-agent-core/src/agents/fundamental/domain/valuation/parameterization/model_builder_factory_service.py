from __future__ import annotations

from collections.abc import Mapping

from ..report_contract import FinancialReport
from .contracts import (
    ModelParamBuilder,
    ParamBuilderPayload,
)
from .model_builder_adapter_service import (
    AssembleResultOp,
    ContextProvider,
    LatestOnlyModelBuilder,
    build_latest_only_model_builder_from_payload,
    build_multi_report_model_builder_from_payload,
)
from .model_builders.context import BuilderContext
from .payload_dispatch_service import (
    DcfVariant,
    EvMultipleVariant,
    MultiReportVariant,
    SingleReportVariant,
    build_dcf_variant_payload,
    build_ev_multiple_payload,
    build_multi_report_payload,
    build_single_report_payload,
)


def build_dcf_variant_model_builder(
    *,
    variant: DcfVariant,
    context_provider: ContextProvider,
    assemble_result: AssembleResultOp,
) -> ModelParamBuilder:
    def _payload_builder(
        context: BuilderContext,
        ticker: str | None,
        latest: FinancialReport,
        reports: list[FinancialReport],
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuilderPayload:
        return build_dcf_variant_payload(
            variant=variant,
            context=context,
            ticker=ticker,
            latest=latest,
            reports=reports,
            market_snapshot=market_snapshot,
        )

    return build_multi_report_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def build_multi_report_model_builder(
    *,
    variant: MultiReportVariant,
    context_provider: ContextProvider,
    assemble_result: AssembleResultOp,
) -> ModelParamBuilder:
    def _payload_builder(
        context: BuilderContext,
        ticker: str | None,
        latest: FinancialReport,
        reports: list[FinancialReport],
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuilderPayload:
        return build_multi_report_payload(
            variant=variant,
            context=context,
            ticker=ticker,
            latest=latest,
            reports=reports,
            market_snapshot=market_snapshot,
        )

    return build_multi_report_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def build_ev_multiple_latest_builder(
    *,
    variant: EvMultipleVariant,
    context_provider: ContextProvider,
    assemble_result: AssembleResultOp,
) -> LatestOnlyModelBuilder:
    def _payload_builder(
        context: BuilderContext,
        ticker: str | None,
        latest: FinancialReport,
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuilderPayload:
        return build_ev_multiple_payload(
            variant=variant,
            context=context,
            ticker=ticker,
            latest=latest,
            market_snapshot=market_snapshot,
        )

    return build_latest_only_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def build_single_report_latest_builder(
    *,
    variant: SingleReportVariant,
    context_provider: ContextProvider,
    assemble_result: AssembleResultOp,
) -> LatestOnlyModelBuilder:
    def _payload_builder(
        context: BuilderContext,
        ticker: str | None,
        latest: FinancialReport,
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuilderPayload:
        return build_single_report_payload(
            variant=variant,
            context=context,
            ticker=ticker,
            latest=latest,
            market_snapshot=market_snapshot,
        )

    return build_latest_only_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )
