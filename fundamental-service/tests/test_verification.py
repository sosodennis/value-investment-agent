import ast
import json
from pathlib import Path

import pytest

from fundamental_service.calculator import calculate
from fundamental_service.verification import (
    VerificationRefusal,
    compare_artifact,
    independent_calculate,
    invariant_findings,
    load_cohort_manifest,
    mutation_findings,
    property_findings,
    request_for_case,
    verify_public_snapshot_bytes,
)
from fundamental_service.verification_gate import run_release_gate

FIXTURE = Path(__file__).parent / "fixtures" / "verification" / "golden_cohort.json"


def test_independent_challenger_does_not_import_production_calculator():
    source = (
        Path(__file__).parents[1] / "src" / "fundamental_service" / "verification.py"
    ).read_text()
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    assert not any(module.endswith(".calculator") for module in imports)


def test_offline_cohort_has_required_counts_and_bound_source_bytes():
    manifest, cases = load_cohort_manifest(FIXTURE)
    assert manifest["cohort_id"] == "fundamental-engineering-cohort-v1"
    assert sum(case.kind == "positive" for case in cases) >= 10
    assert sum(case.kind != "positive" for case in cases) >= 10
    assert (
        sum(case.model_id == "fcff_dcf" and case.kind == "positive" for case in cases)
        >= 5
    )
    assert (
        sum(
            case.model_id == "transition_fcff_dcf" and case.kind == "positive"
            for case in cases
        )
        >= 5
    )
    sources = verify_public_snapshot_bytes(FIXTURE, cases)
    assert {record["snapshot_id"] for record in sources} == {
        "apple-2024-original",
        "tesla-2024-original",
        "tesla-2025-amendment",
    }


def test_release_gate_replays_positive_and_explicit_abstention_cases():
    report = run_release_gate(FIXTURE)
    assert report["release_decision"] == "pass"
    assert report["offline"] is True
    assert report["counts"] == {
        "total": 21,
        "positive": 10,
        "abstain_or_degraded": 11,
        "fcff_dcf_positive": 5,
        "transition_fcff_dcf_positive": 5,
    }
    assert all(
        case["replay"] == "match"
        for case in report["cases"]
        if case["kind"] == "positive"
    )
    assert {
        "extension-heavy",
        "amended-filing",
        "sbc",
        "dilution",
        "share-class",
        "leases",
        "capital-bridge",
        "missing-fact",
        "conflicting-facts",
        "unsupported-sector",
    } <= set(report["feature_coverage"])
    assert report["report_digest"]
    assert report["report_digest"] == run_release_gate(FIXTURE)["report_digest"]


def test_transition_challenger_requires_filed_operating_evidence():
    manifest, cases = load_cohort_manifest(FIXTURE)
    transition = next(
        case
        for case in cases
        if case.model_id == "transition_fcff_dcf" and case.kind == "positive"
    )
    request = request_for_case(manifest, transition)
    missing = request.model_copy(
        update={
            "historical_facts": tuple(
                fact
                for fact in request.historical_facts
                if fact != "filed_operating_evidence"
            )
        }
    )
    with pytest.raises(VerificationRefusal, match="filed operating evidence"):
        independent_calculate(missing)


def test_first_critical_node_mismatch_is_reported():
    manifest, cases = load_cohort_manifest(FIXTURE)
    positive = next(case for case in cases if case.kind == "positive")
    request = request_for_case(manifest, positive)
    artifact = calculate(request)
    mutated_node = artifact.nodes[0].model_copy(
        update={"value": artifact.nodes[0].value + 1}
    )
    mutated = artifact.model_copy(update={"nodes": (mutated_node, *artifact.nodes[1:])})
    findings = compare_artifact(independent_calculate(request), mutated)
    assert findings == ("cost_of_equity:value",)


def test_invariants_properties_and_mutation_sentinels_pass():
    manifest, cases = load_cohort_manifest(FIXTURE)
    positive = next(case for case in cases if case.kind == "positive")
    request = request_for_case(manifest, positive)
    reference = independent_calculate(request)
    assert invariant_findings(request, reference) == ()
    assert property_findings(request) == ()
    assert mutation_findings(request) == ()


def test_report_is_json_serializable_and_does_not_contain_network_dependency():
    report = run_release_gate(FIXTURE)
    encoded = json.dumps(report, sort_keys=True)
    assert "http://" not in encoded
    assert "https://" not in encoded
