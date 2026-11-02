from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.types import JSONObject

from .snapshot_service import (
    env_int,
    env_text,
    market_text,
    merge_metadata,
    parse_iso_datetime,
    to_int,
)


def apply_time_alignment_guard(
    *,
    assumptions: list[str],
    metadata: JSONObject,
    period_end_raw: object,
    market_snapshot: Mapping[str, object],
    default_threshold_days: int,
    default_policy: str,
) -> tuple[list[str], JSONObject]:
    as_of_raw = market_snapshot.get("as_of")
    as_of_dt = parse_iso_datetime(as_of_raw)
    period_end_dt = parse_iso_datetime(period_end_raw)
    if as_of_dt is None or period_end_dt is None:
        return assumptions, metadata

    threshold_days = env_int(
        "FUNDAMENTAL_TIME_ALIGNMENT_MAX_DAYS",
        default_threshold_days,
        minimum=0,
    )
    policy = env_text("FUNDAMENTAL_TIME_ALIGNMENT_POLICY", default_policy)
    snapshot_threshold = to_int(market_snapshot.get("time_alignment_max_days"))
    snapshot_policy = market_text(market_snapshot, "time_alignment_policy")
    if snapshot_threshold is not None and snapshot_threshold >= 0:
        threshold_days = snapshot_threshold
    if snapshot_policy in {"warn", "reject"}:
        policy = snapshot_policy
    if policy not in {"warn", "reject"}:
        policy = default_policy

    lag_days = int((as_of_dt.date() - period_end_dt.date()).days)
    status = "aligned"
    updated_assumptions = list(assumptions)
    if lag_days > threshold_days:
        status = "high_risk"
        updated_assumptions.append(
            "high-risk: market_data_as_of exceeds filing_period_end by "
            f"{lag_days} days (threshold={threshold_days}, policy={policy})"
        )
        if policy == "reject":
            raise ValueError(
                "Time-alignment guard rejected valuation: "
                f"market_data_as_of lag={lag_days} days > threshold={threshold_days}"
            )

    time_alignment: JSONObject = {
        "status": status,
        "policy": policy,
        "lag_days": lag_days,
        "threshold_days": threshold_days,
        "market_as_of": as_of_dt.isoformat(),
        "filing_period_end": period_end_dt.date().isoformat(),
    }
    updated_metadata = merge_metadata(
        metadata,
        {"data_freshness": {"time_alignment": time_alignment}},
    )
    return updated_assumptions, updated_metadata


__all__ = ["apply_time_alignment_guard"]
