from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.shared.contracts.traceable import TraceableField
from src.shared.kernel.tools.logger import log_event

from .base_model_debt_component_extraction_service import (
    DebtComponentFields,
    extract_debt_component_fields,
)
from .base_model_debt_config_service import (
    BuildConfigFn,
    ResolveConfigsFn,
    build_debt_config_bundle,
    relax_debt_config_bundle,
)
from .extractor import SearchConfig, SECReportExtractor

ExtractFieldFn = Callable[
    [SECReportExtractor, list[SearchConfig], str, type[float]],
    TraceableField[float],
]
ResolveTotalDebtPolicyFn = Callable[[], str]
RelaxStatementFiltersFn = Callable[[list[SearchConfig]], list[SearchConfig]]
BuildTotalDebtWithPolicyFn = Callable[
    [
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        str,
    ],
    tuple[TraceableField[float], dict[str, TraceableField[float]], str],
]
BuildRealEstateDebtCombinedFn = Callable[
    [
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
        TraceableField[float],
    ],
    TraceableField[float],
]
FieldSourceLabelFn = Callable[[TraceableField[float]], str]
LogTotalDebtDiagnosticsFn = Callable[
    [str, str, TraceableField[float], dict[str, TraceableField[float]]],
    None,
]


@dataclass(frozen=True)
class DebtBuilderOps:
    extract_field_fn: ExtractFieldFn
    resolve_total_debt_policy_fn: ResolveTotalDebtPolicyFn
    relax_statement_filters_fn: RelaxStatementFiltersFn
    build_total_debt_with_policy_fn: BuildTotalDebtWithPolicyFn
    build_real_estate_debt_combined_ex_leases_fn: BuildRealEstateDebtCombinedFn
    field_source_label_fn: FieldSourceLabelFn
    log_total_debt_diagnostics_fn: LogTotalDebtDiagnosticsFn


def build_total_debt_field(
    *,
    extractor: SECReportExtractor,
    industry_type: str | None,
    resolve_configs: ResolveConfigsFn,
    build_config: BuildConfigFn,
    ops: DebtBuilderOps,
    logger_: logging.Logger,
    bs_statement_tokens: list[str],
    usd_units: list[str],
) -> TraceableField[float]:
    config_bundle = build_debt_config_bundle(
        resolve_configs=resolve_configs,
        build_config=build_config,
        bs_statement_tokens=bs_statement_tokens,
        usd_units=usd_units,
    )

    strict_components = extract_debt_component_fields(
        extractor=extractor,
        industry_type=industry_type,
        config_bundle=config_bundle,
        extract_field_fn=ops.extract_field_fn,
        build_real_estate_debt_combined_ex_leases_fn=ops.build_real_estate_debt_combined_ex_leases_fn,
        field_source_label_fn=ops.field_source_label_fn,
        logger_=logger_,
        relaxed=False,
    )

    debt_policy = ops.resolve_total_debt_policy_fn()
    tf_total_debt, total_debt_components, total_debt_resolution_source = (
        _resolve_total_debt_with_policy(
            ops=ops,
            components=strict_components,
            policy=debt_policy,
        )
    )

    if tf_total_debt.value is None:
        log_event(
            logger_,
            event="fundamental_total_debt_relaxed_search_started",
            message="retrying total debt extraction without statement_type filter",
            level=logging.WARNING,
            fields={"policy": debt_policy},
        )

        relaxed_components = extract_debt_component_fields(
            extractor=extractor,
            industry_type=industry_type,
            config_bundle=relax_debt_config_bundle(
                config_bundle,
                ops.relax_statement_filters_fn,
            ),
            extract_field_fn=ops.extract_field_fn,
            build_real_estate_debt_combined_ex_leases_fn=ops.build_real_estate_debt_combined_ex_leases_fn,
            field_source_label_fn=ops.field_source_label_fn,
            logger_=logger_,
            relaxed=True,
        )

        tf_total_debt_relaxed, total_debt_components_relaxed, relaxed_source = (
            _resolve_total_debt_with_policy(
                ops=ops,
                components=relaxed_components,
                policy=debt_policy,
            )
        )

        log_event(
            logger_,
            event="fundamental_total_debt_relaxed_search_completed",
            message="completed relaxed total debt extraction retry",
            level=logging.WARNING,
            fields={
                "resolved": tf_total_debt_relaxed.value is not None,
                "resolution_source": relaxed_source,
                "total_debt": tf_total_debt_relaxed.value,
            },
        )

        if tf_total_debt_relaxed.value is not None:
            tf_total_debt = tf_total_debt_relaxed
            total_debt_components = total_debt_components_relaxed
            total_debt_resolution_source = f"{relaxed_source}_relaxed_statement_filter"

    ops.log_total_debt_diagnostics_fn(
        policy=debt_policy,
        resolution_source=total_debt_resolution_source,
        total_debt=tf_total_debt,
        components=total_debt_components,
    )
    return tf_total_debt


def _resolve_total_debt_with_policy(
    *,
    ops: DebtBuilderOps,
    components: DebtComponentFields,
    policy: str,
) -> tuple[TraceableField[float], dict[str, TraceableField[float]], str]:
    return ops.build_total_debt_with_policy_fn(
        debt_combined_ex_leases=components.debt_combined_ex_leases,
        debt_short=components.debt_short,
        debt_long=components.debt_long,
        debt_combined_with_leases=components.debt_combined_with_leases,
        finance_lease_combined=components.finance_lease_combined,
        finance_lease_current=components.finance_lease_current,
        finance_lease_noncurrent=components.finance_lease_noncurrent,
        policy=policy,
    )
