"""Shared source checks preserve complete per-proposal mapping decisions."""

import pytest

from fundamental_service import automatic_mapping_evidence as evidence
from fundamental_service import original_issuer
from fundamental_service.arelle_parser import ArelleParseReportV1
from fundamental_service.automatic_mapping import evaluate_automatic_mapping
from fundamental_service.automatic_mapping_evidence import (
    AutomaticMappingEvidenceChecks,
)
from fundamental_service.contracts import IdentityV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_automatic_mapping import case
from test_automatic_mapping_batch import batch_case, read_decision, run_batch


def contents_for(request, store):
    return {
        ref.content_hash: store.read(ref.artifact_id) for ref in request.evidence_refs
    }


def test_shared_original_checks_preserve_each_distinct_proposal(tmp_path, monkeypatch):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    requests = (
        request,
        request.model_copy(
            update={
                "proposal": request.proposal.model_copy(
                    update={"normalized_field": "unsupported-role"}
                )
            }
        ),
        request,
    )
    expected = tuple(evaluate_automatic_mapping(x, contents=contents) for x in requests)
    assert expected[0].status == "approved" and expected[1].status == "abstain"
    original_check = evidence.verify_original_bytes
    calls = []

    def observed(*args, **kwargs):
        calls.append(True)
        return original_check(*args, **kwargs)

    monkeypatch.setattr(evidence, "verify_original_bytes", observed)
    shared = AutomaticMappingEvidenceChecks()
    actual = tuple(
        evaluate_automatic_mapping(x, contents=contents, evidence_checks=shared)
        for x in requests
    )
    assert actual == expected
    assert tuple(map(sha256_digest, actual)) == tuple(map(sha256_digest, expected))
    assert len(calls) == 1
    assert evaluate_automatic_mapping(request, contents=contents) == expected[0]
    assert len(calls) == 2


def test_report_replay_work_is_shared_without_changing_mapping_results(
    tmp_path, monkeypatch
):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    expected = evaluate_automatic_mapping(request, contents=contents)
    calls = []
    replay = ArelleParseReportV1.replay_digest

    def observed(report):
        if report is request.original.report:
            calls.append(True)
        return replay(report)

    monkeypatch.setattr(ArelleParseReportV1, "replay_digest", observed)
    shared = AutomaticMappingEvidenceChecks()
    for _ in range(3):
        assert (
            evaluate_automatic_mapping(
                request, contents=contents, evidence_checks=shared
            )
            == expected
        )
    assert len(calls) == 1
    assert evaluate_automatic_mapping(request, contents=contents) == expected
    assert len(calls) == 2


def test_changed_report_copy_cannot_inherit_a_successful_fingerprint(tmp_path):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    shared = AutomaticMappingEvidenceChecks()
    expected = evaluate_automatic_mapping(request, contents=contents)
    assert expected.status == "approved"
    assert (
        evaluate_automatic_mapping(request, contents=contents, evidence_checks=shared)
        == expected
    )
    report = request.original.report
    facts = tuple(
        fact.model_copy(update={"value": "999999999"})
        if fact.concept == request.proposal.source_concept
        else fact
        for fact in report.facts
    )
    changed = request.model_copy(
        update={
            "original": request.original.model_copy(
                update={"report": report.model_copy(update={"facts": facts})}
            )
        }
    )
    refused = evaluate_automatic_mapping(changed, contents=contents)
    assert refused.status == "abstain"
    assert (
        evaluate_automatic_mapping(changed, contents=contents, evidence_checks=shared)
        == refused
    )
    assert (
        evaluate_automatic_mapping(request, contents=contents, evidence_checks=shared)
        == expected
    )


@pytest.mark.parametrize(
    "limits", ({"max_retained_report_bytes": 0}, {"max_retained_reports": 0})
)
def test_disabled_report_retention_preserves_fingerprints(
    tmp_path, monkeypatch, limits
):
    request, _, _, _ = case(tmp_path)
    report = request.original.report
    expected = report.replay_digest()
    replay = ArelleParseReportV1.replay_digest
    calls = []

    def observed(item):
        calls.append(True)
        return replay(item)

    monkeypatch.setattr(ArelleParseReportV1, "replay_digest", observed)
    shared = AutomaticMappingEvidenceChecks(**limits)
    assert shared.report_replay_digest(report) == expected
    assert shared.report_replay_digest(report) == expected
    assert len(calls) == 2


@pytest.mark.parametrize("limit", ("count", "bytes"))
def test_report_eviction_recomputes_without_changing_digests(
    tmp_path, monkeypatch, limit
):
    request, _, _, _ = case(tmp_path)
    report = request.original.report
    other = report.model_copy(update={"filing_path": report.filing_path + ".other"})
    expected = report.replay_digest()
    replay = ArelleParseReportV1.replay_digest
    calls = []

    def observed(item):
        calls.append(id(item))
        return replay(item)

    monkeypatch.setattr(ArelleParseReportV1, "replay_digest", observed)
    limits = (
        {"max_retained_reports": 1}
        if limit == "count"
        else {
            "max_retained_report_bytes": len(
                canonical_bytes(report.model_dump(mode="json"))
            )
            + len(canonical_bytes(other.model_dump(mode="json")))
            - 1
        }
    )
    shared = AutomaticMappingEvidenceChecks(**limits)
    for item in (report, other, report):
        assert shared.report_replay_digest(item) == expected
    assert calls == [id(report), id(other), id(report)]


@pytest.mark.parametrize(
    "mutation", ("missing", "corrupt", "integrity", "original", "identity", "ref")
)
def test_changed_source_cannot_reuse_a_successful_check(tmp_path, mutation):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    shared = AutomaticMappingEvidenceChecks()
    expected = evaluate_automatic_mapping(request, contents=contents)
    assert expected.status == "approved"
    assert (
        evaluate_automatic_mapping(request, contents=contents, evidence_checks=shared)
        == expected
    )
    changed = request
    altered = dict(contents)
    if mutation == "missing":
        altered.pop(request.integrity.raw_content_hash)
    elif mutation == "corrupt":
        altered[request.integrity.raw_content_hash] = b"changed original"
    elif mutation == "integrity":
        changed = request.model_copy(
            update={
                "integrity": request.integrity.model_copy(
                    update={"raw_content_hash": "f" * 64}
                )
            }
        )
    elif mutation == "original":
        changed = request.model_copy(
            update={
                "original": request.original.model_copy(
                    update={
                        "status": "abstain",
                        "issue_codes": ("ORIGINAL_SOURCE_CHANGED",),
                    }
                )
            }
        )
    elif mutation == "identity":
        changed = request.model_copy(
            update={
                "security_identity": IdentityV1(
                    issuer_id="0000000999",
                    issuer_name="Wrong issuer",
                    domicile="US",
                    reporting_basis="us-gaap",
                    security_id="WRONG",
                    share_class="common",
                    currency="USD",
                )
            }
        )
    else:
        changed = request.model_copy(
            update={
                "evidence_refs": (
                    request.evidence_refs[0].model_copy(
                        update={"content_hash": "f" * 64}
                    ),
                    *request.evidence_refs[1:],
                )
            }
        )
    uncached = evaluate_automatic_mapping(changed, contents=altered)
    assert uncached.status == "abstain"
    assert (
        evaluate_automatic_mapping(changed, contents=altered, evidence_checks=shared)
        == uncached
    )
    assert (
        evaluate_automatic_mapping(request, contents=contents, evidence_checks=shared)
        == expected
    )


def test_every_supplied_byte_and_source_pin_participates_in_reuse(
    tmp_path, monkeypatch
):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    original_check = evidence._source_reasons
    calls = []

    def observed(*args, **kwargs):
        calls.append(True)
        return original_check(*args, **kwargs)

    monkeypatch.setattr(evidence, "_source_reasons", observed)
    shared = AutomaticMappingEvidenceChecks()
    shared.assess(request, contents=contents)
    shared.assess(request, contents=contents)
    assert len(calls) == 1
    for pin, value in (("source_revision", "b" * 40), ("evaluator_id", "other")):
        shared.assess(request.model_copy(update={pin: value}), contents=contents)
    extra = {**contents, "additional": b"one"}
    shared.assess(request, contents=extra)
    extra["additional"] = b"two"
    shared.assess(request, contents=extra)
    assert len(calls) == 5


def test_batch_shares_source_checks_but_new_batch_revalidates(tmp_path, monkeypatch):
    request, store, roots = batch_case(tmp_path)
    original_check = evidence.verify_original_bytes
    calls = []
    original_digest = original_issuer._issuer_input_digest
    semantic_calls = []

    def observed(*args, **kwargs):
        calls.append(True)
        return original_check(*args, **kwargs)

    def semantic_check(*args, **kwargs):
        semantic_calls.append(True)
        return original_digest(*args, **kwargs)

    monkeypatch.setattr(evidence, "verify_original_bytes", observed)
    monkeypatch.setattr(original_issuer, "_issuer_input_digest", semantic_check)
    first = run_batch(request, store, roots)
    assert len(first.mapping_receipts) > 1
    assert len(calls) == 1
    assert len(semantic_calls) == 1
    decision = read_decision(first, store)
    roles = {x.normalized_field: x.status for x in decision.roles}
    assert roles["revenue"] == "approved"
    assert roles["capital_expenditure"] == "abstain"
    second = run_batch(request, store, roots)
    assert len(calls) == 2
    assert len(semantic_calls) == 2
    assert not second.wrote and second.output_digest == first.output_digest


def test_source_reuse_does_not_rehash_exact_immutable_bytes(tmp_path, monkeypatch):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    expected = AutomaticMappingEvidenceChecks().assess(request, contents=contents)
    hashed = []
    real_sha256 = evidence.hashlib.sha256

    def observed(raw=b"", *args, **kwargs):
        if any(raw is item for item in contents.values()):
            hashed.append(id(raw))
        return real_sha256(raw, *args, **kwargs)

    monkeypatch.setattr(evidence.hashlib, "sha256", observed)
    checks = AutomaticMappingEvidenceChecks()
    assert checks.assess(request, contents=contents) == expected
    first_work = len(hashed)
    assert first_work > 0
    for _ in range(16):
        assert checks.assess(request, contents=dict(contents)) == expected
    assert len(hashed) == first_work
    changed = dict(contents)
    key = request.evidence_refs[0].content_hash
    changed[key] = b"!" + changed[key][1:]
    assert "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE" in checks.assess(
        request, contents=changed
    )
    assert checks.assess(request, contents=contents) == expected
    assert (
        AutomaticMappingEvidenceChecks().assess(request, contents=contents) == expected
    )
    assert len(hashed) > first_work


@pytest.mark.parametrize(
    "limits",
    (
        {"max_retained_bytes": 0},
        {"max_retained_artifacts": 0},
        {"max_retained_artifacts": 1},
    ),
)
def test_source_fingerprint_eviction_or_disabled_retention_preserves_refusals(
    tmp_path, limits
):
    request, store, _, _ = case(tmp_path)
    contents = contents_for(request, store)
    checks = AutomaticMappingEvidenceChecks(**limits)
    expected = AutomaticMappingEvidenceChecks().assess(request, contents=contents)
    for _ in range(4):
        assert checks.assess(request, contents=contents) == expected
    key = request.evidence_refs[0].content_hash
    mutable = bytearray(contents[key])
    supplied = {**contents, key: mutable}
    assert checks.assess(request, contents=supplied) == expected
    mutable[0] ^= 1
    assert "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE" in checks.assess(
        request, contents=supplied
    )
