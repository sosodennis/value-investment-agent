"""Referenced parser reports are checked once inside an owner operation."""

import json

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import ArelleParseReportV1
from fundamental_service.automatic_mapping import AutomaticMappingRequestV1
from fundamental_service.automatic_mapping_runner import approve_mapping
from fundamental_service.mapping_input_storage import resolve_mapping_input
from fundamental_service.original_issuer import (
    OriginalIssuerEvidenceChecks,
    OriginalIssuerEvidenceV1,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_mapping import MACHINE_KEY, case


def retained(tmp_path):
    request, store, roots, _ = case(tmp_path)
    receipt = approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    raw = store.read(receipt.input_publication.artifact.artifact_id)
    return request, store, raw


def resolve(raw, store, checks):
    return resolve_mapping_input(
        raw, AutomaticMappingRequestV1, artifacts=store, original_checks=checks
    )


def test_distinct_mapping_inputs_share_immutable_report_but_not_original_metadata(
    tmp_path, monkeypatch
):
    request, store, raw = retained(tmp_path)
    parse = ArelleParseReportV1.model_validate_json
    calls = []

    def counted(value, **kwargs):
        calls.append(True)
        return parse(value, **kwargs)

    monkeypatch.setattr(ArelleParseReportV1, "model_validate_json", counted)
    checks = OriginalIssuerEvidenceChecks()
    first = resolve(raw, store, checks)
    changed = json.loads(raw)
    changed["request"]["source_revision"] = "b" * 40
    expected = request.model_copy(update={"source_revision": "b" * 40})
    changed["input_digest"] = sha256_digest(expected)
    second = resolve(canonical_bytes(changed), store, checks)
    assert first == request and second == expected
    assert sha256_digest(second) == changed["input_digest"]
    assert first.original is not second.original
    assert first.original.source is not second.original.source
    assert first.original.report is second.original.report
    assert len(calls) == 1
    with pytest.raises(ValidationError, match="frozen"):
        second.original.report.facts[0].value = "changed"
    third = resolve(raw, store, OriginalIssuerEvidenceChecks())
    assert third == first and third.original.report is not first.original.report
    assert len(calls) == 2


@pytest.mark.parametrize(
    "context", [None, {"validated": True}, OriginalIssuerEvidenceChecks()]
)
def test_serialized_or_plain_context_cannot_hydrate_a_missing_report(tmp_path, context):
    request, _, _ = retained(tmp_path)
    value = request.original.model_dump(mode="json")
    value["report"] = None
    with pytest.raises(ValidationError):
        OriginalIssuerEvidenceV1.model_validate_json(
            canonical_bytes(value), context=context
        )


@pytest.mark.parametrize(
    "field", ["decision_at", "identity", "input_digest", "output_digest"]
)
def test_report_reuse_does_not_admit_changed_issuer_claims(tmp_path, field):
    _, store, raw = retained(tmp_path)
    checks = OriginalIssuerEvidenceChecks()
    resolve(raw, store, checks)
    changed = json.loads(raw)
    if field == "decision_at":
        changed["original"][field] = (
            changed["original"][field].replace("Z", "").replace("+00:00", "")
        )
    elif field == "identity":
        changed["original"][field]["issuer_id"] = "0000000999"
    else:
        changed["original"][field] = "0" * 64
    for _ in range(2):
        with pytest.raises(ValidationError):
            resolve(canonical_bytes(changed), store, checks)
    assert resolve(raw, store, checks).original.status == "matched"


@pytest.mark.parametrize(
    "limits", [{"max_reports": 0}, {"max_report_bytes": 0}, {"max_report_facts": 0}]
)
def test_oversized_reports_validate_without_retention(tmp_path, limits):
    _, store, raw = retained(tmp_path)
    checks = OriginalIssuerEvidenceChecks(**limits)
    first, second = resolve(raw, store, checks), resolve(raw, store, checks)
    assert first == second
    assert first.original.report is not second.original.report


@pytest.mark.parametrize(
    "limit", ["max_reports", "max_report_bytes", "max_report_facts"]
)
def test_eviction_reloads_without_changing_semantics(tmp_path, limit):
    request, _, _ = retained(tmp_path)
    raw = canonical_bytes(request.original.report.model_dump(mode="json"))
    changed = json.loads(raw)
    changed["filing_path"] += "-different"
    other = canonical_bytes(changed)
    bound = {
        "max_reports": 1,
        "max_report_bytes": max(len(raw), len(other)),
        "max_report_facts": len(request.original.report.facts),
    }[limit]
    checks = OriginalIssuerEvidenceChecks(**{limit: bound})
    first = checks.resolve_report(raw).report
    assert checks.resolve_report(raw).report is first
    checks.resolve_report(other)
    third = checks.resolve_report(raw).report
    assert third == first and third is not first


@pytest.mark.parametrize(
    "limit", ["max_reports", "max_report_bytes", "max_report_facts"]
)
def test_negative_retention_limits_refuse(limit):
    with pytest.raises(ValueError, match="nonnegative"):
        OriginalIssuerEvidenceChecks(**{limit: -1})
