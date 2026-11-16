"""Research freeze refuses drift and authority escalation, and reuses reports."""

import json
import sys
from pathlib import Path

import pytest

from fundamental_service.serialization import canonical_bytes

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import freeze_history_analysis as freezer  # noqa: E402
from plan_history_study_precision import publish_report  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "docs/research/issue-377-analysis-freeze-v1.json"


def test_complete_frozen_dependencies_and_repeated_artifact(tmp_path):
    raw = FREEZE.read_bytes()
    freeze = freezer.verify_freeze(raw, root=ROOT)
    assert freeze.promotion_enabled is False
    assert freeze.supported_history_threshold is None
    assert freeze.legacy_gate_changed is False
    first = publish_report(tmp_path, json.loads(raw))
    file = tmp_path / (first["report_digest"] + ".json")
    before = (file.read_bytes(), file.stat().st_mtime_ns)
    second = publish_report(tmp_path, json.loads(raw))
    assert first["wrote"] is True
    assert second == {**first, "wrote": False}
    assert (file.read_bytes(), file.stat().st_mtime_ns) == before
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("promotion_enabled", True),
        ("supported_history_threshold", 3),
        ("legacy_gate_changed", True),
        ("legacy_minimum_complete_pairs", 90),
        ("fixed_manifest_digest", "0" * 64),
        ("independent_review_claim", True),
        ("prospective_power_claim", True),
        ("review_status", "externally_approved"),
        ("precision_claim", "0.10_MASE_approved"),
    ],
)
def test_manifest_cannot_grant_authority_or_substitute_scope(field, value):
    payload = json.loads(FREEZE.read_bytes())
    payload[field] = value
    with pytest.raises(ValueError):
        freezer.verify_freeze(canonical_bytes(payload) + b"\n", root=ROOT)


@pytest.mark.parametrize("fault", ["changed", "omitted", "extra", "noncanonical"])
def test_drift_and_incomplete_freeze_refused(fault):
    payload = json.loads(FREEZE.read_bytes())
    name = freezer.DEPENDENCIES[0]
    if fault == "changed":
        payload["method_dependencies"][name] = "0" * 64
    elif fault == "omitted":
        del payload["method_dependencies"][name]
    elif fault == "extra":
        payload["method_dependencies"]["unreviewed.py"] = "0" * 64
    raw = canonical_bytes(payload) + b"\n"
    if fault == "noncanonical":
        raw += b"\n"
    with pytest.raises(ValueError):
        freezer.verify_freeze(raw, root=ROOT)
