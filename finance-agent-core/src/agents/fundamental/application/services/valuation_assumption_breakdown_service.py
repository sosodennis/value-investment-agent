from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject

from .valuation_data_freshness_service import extract_time_alignment_status
from .valuation_distribution_preview_service import extract_distribution_summary


def build_assumption_breakdown(
    *,
    assumptions: list[str],
    params_dump: JSONObject,
    calculation_metrics: JSONObject,
    build_metadata: JSONObject | None = None,
) -> JSONObject:
    assumption_items: list[JSONObject] = []
    has_high_severity = False
    for statement in assumptions:
        category = "policy"
        severity = "medium"
        normalized = statement.lower()
        if "defaulted" in normalized:
            category = "default"
            severity = "high"
        elif "blended" in normalized:
            category = "blended"
            severity = "medium"
        elif "high-risk" in normalized or "time-alignment" in normalized:
            category = "risk"
            severity = "high"

        assumption_items.append(
            {
                "statement": statement,
                "category": category,
                "severity": severity,
            }
        )
        if severity == "high":
            has_high_severity = True

    key_parameter_fields = (
        "wacc",
        "terminal_growth",
        "risk_free_rate",
        "beta",
        "market_risk_premium",
        "maintenance_capex_ratio",
        "cost_of_equity_strategy",
        "current_price",
    )
    key_parameters: JSONObject = {}
    for field in key_parameter_fields:
        value = params_dump.get(field)
        if isinstance(value, str | int | float | bool):
            key_parameters[field] = value

    distribution_summary = extract_distribution_summary(calculation_metrics)
    iterations_value = params_dump.get("monte_carlo_iterations")
    seed_value = params_dump.get("monte_carlo_seed")
    monte_carlo_enabled = False
    if isinstance(iterations_value, int) and iterations_value > 0:
        monte_carlo_enabled = True
    if distribution_summary is not None:
        monte_carlo_enabled = True

    monte_carlo: JSONObject = {"enabled": monte_carlo_enabled}
    if isinstance(iterations_value, int):
        monte_carlo["iterations"] = iterations_value
    if isinstance(seed_value, int):
        monte_carlo["seed"] = seed_value
    if distribution_summary is not None:
        diagnostics = distribution_summary.get("diagnostics")
        if isinstance(diagnostics, Mapping):
            mc_diagnostic_fields = (
                "sampler_type",
                "sampler_requested",
                "sampler_fallback_used",
                "sampler_fallback_reason",
                "batch_evaluator_used",
                "executed_iterations",
                "configured_iterations",
                "effective_window",
                "stopped_early",
                "converged",
                "sufficient_window",
                "psd_repaired",
                "psd_repaired_groups",
                "psd_repair_failed_groups",
                "psd_repair_clip_used",
                "psd_repair_higham_used",
                "psd_min_eigen_before",
                "psd_min_eigen_after",
                "corr_diagnostics_available",
                "corr_pairs_total",
                "corr_pearson_mae",
                "corr_pearson_max_abs_error",
                "corr_spearman_mae",
                "corr_spearman_max_abs_error",
            )
            for field in mc_diagnostic_fields:
                value = diagnostics.get(field)
                if isinstance(value, bool):
                    monte_carlo[field] = value
                elif isinstance(value, int):
                    monte_carlo[field] = value
                elif isinstance(value, float):
                    monte_carlo[field] = value
                elif isinstance(value, str):
                    monte_carlo[field] = value

    if isinstance(build_metadata, Mapping):
        data_freshness_raw = build_metadata.get("data_freshness")
        if isinstance(data_freshness_raw, Mapping):
            time_alignment_raw = data_freshness_raw.get("time_alignment")
            if isinstance(time_alignment_raw, Mapping):
                for field in (
                    "status",
                    "policy",
                    "lag_days",
                    "threshold_days",
                    "market_as_of",
                    "filing_period_end",
                ):
                    value = time_alignment_raw.get(field)
                    if isinstance(value, str | int | float | bool):
                        key_parameters[f"time_alignment_{field}"] = value

    data_quality_flags = _collect_data_quality_flags(
        assumptions=assumptions,
        build_metadata=build_metadata,
    )
    time_alignment_status = extract_time_alignment_status(build_metadata)
    if time_alignment_status is not None:
        key_parameters["time_alignment_status"] = time_alignment_status

    assumption_risk_level = "high" if has_high_severity else "medium"
    if time_alignment_status == "high_risk":
        assumption_risk_level = "high"
    if assumption_risk_level != "high" and data_quality_flags:
        assumption_risk_level = "medium"

    forward_signal_summary: JSONObject | None = None
    forward_signal_risk_level: str | None = None
    forward_signal_evidence_count: int | None = None
    audit_summary: JSONObject | None = None
    parameter_source_summary: JSONObject | None = None
    if isinstance(build_metadata, Mapping):
        forward_signal_raw = build_metadata.get("forward_signal")
        if isinstance(forward_signal_raw, Mapping):
            forward_signal_payload: JSONObject = {}
            for field in (
                "signals_total",
                "signals_accepted",
                "signals_rejected",
                "evidence_count",
                "growth_adjustment_basis_points",
                "margin_adjustment_basis_points",
                "risk_level",
                "source_types",
                "decisions",
            ):
                value = forward_signal_raw.get(field)
                if isinstance(value, bool):
                    forward_signal_payload[field] = value
                elif isinstance(value, int | float | str):
                    forward_signal_payload[field] = value
                elif isinstance(value, list):
                    forward_signal_payload[field] = value
            if forward_signal_payload:
                forward_signal_summary = forward_signal_payload
                risk_raw = forward_signal_raw.get("risk_level")
                if isinstance(risk_raw, str) and risk_raw:
                    forward_signal_risk_level = risk_raw
                evidence_raw = forward_signal_raw.get("evidence_count")
                if isinstance(evidence_raw, int):
                    forward_signal_evidence_count = evidence_raw
                elif isinstance(evidence_raw, float):
                    forward_signal_evidence_count = int(evidence_raw)

        audit_raw = build_metadata.get("audit")
        if isinstance(audit_raw, Mapping):
            passed_raw = audit_raw.get("passed")
            message_count_raw = audit_raw.get("message_count")
            warn_count_raw = audit_raw.get("warn_count")
            fail_count_raw = audit_raw.get("fail_count")
            messages_raw = audit_raw.get("messages")
            summary_payload: JSONObject = {}
            if isinstance(passed_raw, bool):
                summary_payload["passed"] = passed_raw
            if isinstance(message_count_raw, int):
                summary_payload["message_count"] = max(message_count_raw, 0)
            if isinstance(warn_count_raw, int):
                summary_payload["warn_count"] = max(warn_count_raw, 0)
            if isinstance(fail_count_raw, int):
                summary_payload["fail_count"] = max(fail_count_raw, 0)
            if isinstance(messages_raw, list):
                messages = [
                    item
                    for item in messages_raw
                    if isinstance(item, str) and item.strip()
                ]
                if messages:
                    summary_payload["messages"] = messages
            if summary_payload:
                audit_summary = summary_payload
        parameter_source_raw = build_metadata.get("parameter_source_summary")
        if isinstance(parameter_source_raw, Mapping):
            parameter_source_summary = dict(parameter_source_raw)

    if isinstance(audit_summary, Mapping):
        fail_count = audit_summary.get("fail_count")
        warn_count = audit_summary.get("warn_count")
        if isinstance(fail_count, int) and fail_count > 0:
            assumption_risk_level = "high"
        elif (
            isinstance(warn_count, int)
            and warn_count > 0
            and assumption_risk_level != "high"
        ):
            assumption_risk_level = "medium"

    if forward_signal_risk_level == "high":
        assumption_risk_level = "high"
    elif forward_signal_risk_level == "medium" and assumption_risk_level != "high":
        assumption_risk_level = "medium"

    if (
        not assumptions
        and not data_quality_flags
        and time_alignment_status not in {"high_risk", "warning"}
        and forward_signal_risk_level not in {"medium", "high"}
    ):
        assumption_risk_level = "low"

    output: JSONObject = {
        "total_assumptions": len(assumption_items),
        "assumptions": assumption_items,
        "key_parameters": key_parameters,
        "monte_carlo": monte_carlo,
        "assumption_risk_level": assumption_risk_level,
        "data_quality_flags": data_quality_flags,
        "time_alignment_status": time_alignment_status,
    }
    if forward_signal_summary is not None:
        output["forward_signal_summary"] = forward_signal_summary
    if forward_signal_risk_level is not None:
        output["forward_signal_risk_level"] = forward_signal_risk_level
    if forward_signal_evidence_count is not None:
        output["forward_signal_evidence_count"] = forward_signal_evidence_count
    if audit_summary is not None:
        output["audit_summary"] = audit_summary
    if parameter_source_summary is not None:
        output["parameter_source_summary"] = parameter_source_summary
    return output


def _collect_data_quality_flags(
    *,
    assumptions: list[str],
    build_metadata: Mapping[str, object] | None,
) -> list[str]:
    flags: list[str] = []

    if any("defaulted" in statement.lower() for statement in assumptions):
        flags.append("defaults_present")

    if not isinstance(build_metadata, Mapping):
        return flags

    data_freshness = build_metadata.get("data_freshness")
    if not isinstance(data_freshness, Mapping):
        return flags

    market_data = data_freshness.get("market_data")
    if isinstance(market_data, Mapping):
        missing_fields_raw = market_data.get("missing_fields")
        if isinstance(missing_fields_raw, list):
            for item in missing_fields_raw:
                if isinstance(item, str) and item:
                    flags.append(f"market_data_missing:{item}")
        quality_flags_raw = market_data.get("quality_flags")
        if isinstance(quality_flags_raw, list):
            for item in quality_flags_raw:
                if isinstance(item, str) and item:
                    flags.append(f"market_data_quality:{item}")

    shares_source = data_freshness.get("shares_outstanding_source")
    if isinstance(shares_source, str) and shares_source:
        if shares_source != "market_data":
            flags.append(f"shares_source:{shares_source}")

    time_alignment = data_freshness.get("time_alignment")
    if isinstance(time_alignment, Mapping):
        status = time_alignment.get("status")
        if isinstance(status, str) and status:
            flags.append(f"time_alignment:{status}")

    return list(dict.fromkeys(flags))
