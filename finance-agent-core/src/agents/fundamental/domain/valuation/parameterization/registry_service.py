from __future__ import annotations

from functools import lru_cache

from ..policies.growth_assumption_policy import (
    DEFAULT_HIGH_GROWTH_TRIGGER,
    DEFAULT_LONG_RUN_GROWTH_TARGET,
)
from .contracts import ModelParamBuilder
from .default_context_service import (
    build_default_builder_context as _build_default_builder_context_service,
)
from .model_builder_factory_service import (
    build_dcf_variant_model_builder as _build_dcf_variant_model_builder_service,
)
from .model_builder_factory_service import (
    build_ev_multiple_latest_builder as _build_ev_multiple_latest_builder_service,
)
from .model_builder_factory_service import (
    build_multi_report_model_builder as _build_multi_report_model_builder_service,
)
from .model_builder_factory_service import (
    build_single_report_latest_builder as _build_single_report_latest_builder_service,
)
from .model_builders.context import BuilderContext
from .result_assembly_service import (
    build_param_result as _build_param_result_service,
)
from .wiring_service import (
    build_model_builder_registry as _build_model_builder_registry_service,
)

PROJECTION_YEARS = 5
DEFAULT_MARKET_RISK_PREMIUM = 0.05
DEFAULT_MAINTENANCE_CAPEX_RATIO = 0.8
DEFAULT_MONTE_CARLO_ITERATIONS = 300
DEFAULT_MONTE_CARLO_SEED = 42
DEFAULT_MONTE_CARLO_SAMPLER = "sobol"


def get_model_builder(model_type: str) -> ModelParamBuilder | None:
    return _model_builder_registry().get(model_type)


@lru_cache(maxsize=1)
def _model_builder_registry() -> dict[str, ModelParamBuilder]:
    return _build_model_builder_registry_service(
        dcf_standard=_build_dcf_variant_model_builder_service(
            variant="dcf_standard",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        dcf_growth=_build_dcf_variant_model_builder_service(
            variant="dcf_growth",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        saas=_build_multi_report_model_builder_service(
            variant="saas",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        bank=_build_multi_report_model_builder_service(
            variant="bank",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        ev_revenue=_build_ev_multiple_latest_builder_service(
            variant="ev_revenue",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        ev_ebitda=_build_ev_multiple_latest_builder_service(
            variant="ev_ebitda",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        reit_ffo=_build_single_report_latest_builder_service(
            variant="reit_ffo",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        residual_income=_build_single_report_latest_builder_service(
            variant="residual_income",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
        eva=_build_single_report_latest_builder_service(
            variant="eva",
            context_provider=_builder_context,
            assemble_result=_build_param_result_service,
        ),
    )


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
