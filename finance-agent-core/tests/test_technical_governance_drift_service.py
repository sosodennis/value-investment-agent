from src.agents.technical.subdomains.governance.domain.drift_service import (
    compare_registry_payloads,
)


def test_compare_registry_payloads_detects_drift() -> None:
    baseline = {
        "fusion_model_version": "v1",
        "calibration_config": {"mapping_bins": [[0.5, 0.55]]},
    }
    current = {
        "fusion_model_version": "v2",
        "calibration_config": {"mapping_bins": [[0.5, 0.60]]},
    }
    drifts, issues = compare_registry_payloads(baseline=baseline, current=current)
    assert len(drifts) == 2
    assert "governance_registry_drift_detected" in issues
