from __future__ import annotations

import math


def safe_float(value: object) -> float | None:
    try:
        numeric_value = float(value)
    except (ValueError, TypeError):
        return None

    if math.isnan(numeric_value) or math.isinf(numeric_value):
        return None
    return numeric_value


def derive_statistical_state(z_score: object) -> str:
    z_value = abs(safe_float(z_score) or 0.0)
    if z_value >= 2.0:
        return "anomaly"
    if z_value >= 1.0:
        return "deviating"
    return "equilibrium"


def derive_memory_strength(optimal_d: object) -> str:
    d_value = safe_float(optimal_d) or 0.5
    if d_value < 0.3:
        return "structurally_stable"
    if d_value > 0.6:
        return "fragile"
    return "balanced"
