"""Shared source checks preserve complete per-proposal mapping decisions."""

import pytest

from fundamental_service import automatic_mapping_evidence as evidence
from fundamental_service import original_issuer
from fundamental_service.automatic_mapping import evaluate_automatic_mapping
from fundamental_service.automatic_mapping_evidence import (
    AutomaticMappingEvidenceChecks,
)
from fundamental_service.contracts import IdentityV1
from fundamental_service.serialization import sha256_digest
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
