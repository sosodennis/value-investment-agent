from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Literal, cast

from src.shared.kernel.tools.logger import log_event
from src.shared.kernel.traceable import TraceableField

TotalDebtPolicy = Literal["include_finance_leases", "exclude_finance_leases"]


def resolve_total_debt_policy(
    *,
    env_var: str,
    default_policy: TotalDebtPolicy,
    logger_: logging.Logger,
) -> TotalDebtPolicy:
    raw_policy = os.getenv(env_var, default_policy).strip()
    normalized = raw_policy.lower()
    if normalized in {"include_finance_leases", "exclude_finance_leases"}:
        return cast(TotalDebtPolicy, normalized)

    log_event(
        logger_,
        event="fundamental_total_debt_policy_invalid",
        message="invalid total debt policy; fallback to default",
        level=logging.WARNING,
        error_code="FUNDAMENTAL_TOTAL_DEBT_POLICY_INVALID",
        fields={
            "env_var": env_var,
            "raw_value": raw_policy,
            "fallback_policy": default_policy,
        },
    )
    return default_policy


def log_total_debt_diagnostics(
    *,
    policy: TotalDebtPolicy,
    resolution_source: str,
    total_debt: TraceableField[float],
    components: dict[str, TraceableField[float]],
    field_source_label_fn: Callable[[TraceableField[float]], str],
    logger_: logging.Logger,
) -> None:
    component_values: dict[str, float | None] = {}
    component_sources: dict[str, str] = {}
    for key, field in components.items():
        component_values[key] = field.value
        component_sources[key] = field_source_label_fn(field)

    log_event(
        logger_,
        event="fundamental_total_debt_policy_applied",
        message="total debt policy resolved",
        fields={
            "policy": policy,
            "resolution_source": resolution_source,
            "total_debt": total_debt.value,
            "total_debt_source": field_source_label_fn(total_debt),
            "component_values": component_values,
            "component_sources": component_sources,
        },
    )

    if total_debt.value is None:
        log_event(
            logger_,
            event="fundamental_total_debt_unresolved",
            message="total debt remains missing after policy resolution",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_TOTAL_DEBT_UNRESOLVED",
            fields={
                "policy": policy,
                "resolution_source": resolution_source,
                "component_values": component_values,
            },
        )
