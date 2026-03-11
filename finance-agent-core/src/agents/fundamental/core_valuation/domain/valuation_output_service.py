from __future__ import annotations

from collections.abc import Mapping


def extract_equity_value_from_metrics(
    calculation_metrics: Mapping[str, object],
) -> object | None:
    intrinsic_value = calculation_metrics.get("intrinsic_value")
    if intrinsic_value is not None:
        return intrinsic_value
    equity_value = calculation_metrics.get("equity_value")
    if equity_value is not None:
        return equity_value
    return None


__all__ = ["extract_equity_value_from_metrics"]
