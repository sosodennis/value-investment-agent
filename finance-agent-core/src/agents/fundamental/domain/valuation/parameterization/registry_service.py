from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import lru_cache

from ..policies.growth_assumption_policy import (
    DEFAULT_HIGH_GROWTH_TRIGGER,
    DEFAULT_LONG_RUN_GROWTH_TARGET,
)
from ..report_contract import FinancialReport
from .contracts import ModelParamBuilder, ParamBuilderPayload, ParamBuildResult
from .default_context_service import (
    build_default_builder_context as _build_default_builder_context_service,
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
from .result_assembly_service import (
    build_param_result as _build_param_result_service,
)

PROJECTION_YEARS = 5
DEFAULT_MARKET_RISK_PREMIUM = 0.05
DEFAULT_MAINTENANCE_CAPEX_RATIO = 0.8
DEFAULT_MONTE_CARLO_ITERATIONS = 300
DEFAULT_MONTE_CARLO_SEED = 42
DEFAULT_MONTE_CARLO_SAMPLER = "sobol"

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


def get_model_builder(model_type: str) -> ModelParamBuilder | None:
    return _model_builder_registry().get(model_type)


def _build_multi_report_model_builder_from_payload(
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


def _build_latest_only_model_builder_from_payload(
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


def _build_dcf_variant_model_builder(
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

    return _build_multi_report_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def _build_multi_report_model_builder(
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

    return _build_multi_report_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def _build_ev_multiple_latest_builder(
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

    return _build_latest_only_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def _build_single_report_latest_builder(
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

    return _build_latest_only_model_builder_from_payload(
        payload_builder=_payload_builder,
        context_provider=context_provider,
        assemble_result=assemble_result,
    )


def _route_latest_only(builder: LatestOnlyModelBuilder) -> ModelParamBuilder:
    def _route(
        ticker: str | None,
        latest: FinancialReport,
        _reports: list[FinancialReport],
        market_snapshot: Mapping[str, object] | None,
    ) -> ParamBuildResult:
        return builder(
            ticker=ticker,
            latest=latest,
            market_snapshot=market_snapshot,
        )

    return _route


@lru_cache(maxsize=1)
def _model_builder_registry() -> dict[str, ModelParamBuilder]:
    return {
        "dcf_standard": _build_dcf_variant_model_builder(
            variant="dcf_standard",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        "dcf_growth": _build_dcf_variant_model_builder(
            variant="dcf_growth",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        "saas": _build_multi_report_model_builder(
            variant="saas",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        "bank": _build_multi_report_model_builder(
            variant="bank",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        "ev_revenue": _route_latest_only(
            _build_ev_multiple_latest_builder(
                variant="ev_revenue",
                context_provider=_builder_context,
                assemble_result=_build_param_result_service,
            )
        ),
        "ev_ebitda": _route_latest_only(
            _build_ev_multiple_latest_builder(
                variant="ev_ebitda",
                context_provider=_builder_context,
                assemble_result=_build_param_result_service,
            )
        ),
        "reit_ffo": _route_latest_only(
            _build_single_report_latest_builder(
                variant="reit_ffo",
                context_provider=_builder_context,
                assemble_result=_build_param_result_service,
            )
        ),
        "residual_income": _route_latest_only(
            _build_single_report_latest_builder(
                variant="residual_income",
                context_provider=_builder_context,
                assemble_result=_build_param_result_service,
            )
        ),
        "eva": _route_latest_only(
            _build_single_report_latest_builder(
                variant="eva",
                context_provider=_builder_context,
                assemble_result=_build_param_result_service,
            )
        ),
    }


@lru_cache(maxsize=1)
def _builder_context() -> BuilderContext:
    return _build_default_builder_context_service(
        projection_years=PROJECTION_YEARS,
        default_market_risk_premium=DEFAULT_MARKET_RISK_PREMIUM,
        default_maintenance_capex_ratio=DEFAULT_MAINTENANCE_CAPEX_RATIO,
        default_monte_carlo_iterations=DEFAULT_MONTE_CARLO_ITERATIONS,
        default_monte_carlo_seed=DEFAULT_MONTE_CARLO_SEED,
        default_monte_carlo_sampler=DEFAULT_MONTE_CARLO_SAMPLER,
        long_run_growth_target=DEFAULT_LONG_RUN_GROWTH_TARGET,
        high_growth_trigger=DEFAULT_HIGH_GROWTH_TRIGGER,
    )
