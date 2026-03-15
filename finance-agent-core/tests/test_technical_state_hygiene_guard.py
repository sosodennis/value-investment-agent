from __future__ import annotations

import pandas as pd

from src.agents.technical.application.state_updates import (
    build_feature_compute_success_update,
)


def test_state_update_guard_rejects_pandas_payload() -> None:
    update = build_feature_compute_success_update(
        feature_pack_id="feature-1",
        artifact={
            "kind": "technical_analysis.output",
            "summary": "bad",
            "preview": pd.DataFrame({"a": [1, 2]}),
        },
    )

    assert update["node_statuses"]["technical_analysis"] == "error"
    assert (
        "State payload contains disallowed pandas objects"
        in update["error_logs"][0]["error"]
    )


def test_state_update_guard_allows_plain_payload() -> None:
    update = build_feature_compute_success_update(
        feature_pack_id="feature-1",
        artifact={
            "kind": "technical_analysis.output",
            "summary": "ok",
            "preview": {"count": 1},
        },
    )

    assert update["node_statuses"]["technical_analysis"] == "running"
