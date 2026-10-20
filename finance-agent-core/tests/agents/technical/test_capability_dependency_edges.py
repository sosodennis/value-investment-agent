from __future__ import annotations

import math

import pandas as pd

from src.agents.technical.subdomains.features.public import serialize_fracdiff_outputs


def test_fracdiff_serialization_keeps_finite_number_contract() -> None:
    result = serialize_fracdiff_outputs(
        fd_series=pd.Series(
            [1.25, math.nan, "invalid"],
            index=["2026-03-01", "2026-03-02", "2026-03-03"],
        ),
        z_score_series=pd.Series([0.5], index=["2026-03-01"]),
        bollinger_data={"upper": "12.5", "middle": 10, "lower": None},
        stat_strength_data={"value": "0.75"},
        obv_data={"raw_obv_val": math.inf, "fd_obv_z": -1.5, "optimal_d": 0.4},
    )

    assert result.bollinger.to_dict() == {
        "upper": 12.5,
        "middle": 10.0,
        "lower": None,
        "state": "INSIDE",
        "bandwidth": None,
    }
    assert result.stat_strength.to_dict() == {"value": 0.75}
    assert result.obv.to_dict() == {
        "raw_obv_val": None,
        "fd_obv_z": -1.5,
        "optimal_d": 0.4,
        "state": "NEUTRAL",
    }
    assert result.fracdiff_series == {
        "2026-03-01": 1.25,
        "2026-03-02": None,
        "2026-03-03": None,
    }
    assert result.z_score_series == {"2026-03-01": 0.5}
