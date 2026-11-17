"""Semantic mappings stay stable while exact execution proofs remain distinct."""

from datetime import timedelta, timezone
from pathlib import Path

import pytest

from fundamental_service.arelle_parser import ArelleFindingV1
from fundamental_service.automatic_mapping import (
    automatic_mapping_policy_digest,
)
from fundamental_service.mapping_computation import mapping_computation_digest
from fundamental_service.mapping_input_identity import MappingInputDigests
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.parser_computation import parser_computation
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import case, evaluate


def rebuilt(request, execution, *, catalog_root=None, offset=None):
    report = request.original.report
    raw = report.model_copy(
        update={
            "filing_path": f"/tmp/worker-{execution}/filing.xml",
            "parsed_at": report.parsed_at + timedelta(seconds=execution),
            "validation_evidence": (
                "strict-sec-efm-profile-selected",
                "dqc-dqcrt-checks-completed",
                f"sec-parser-action-v2:normalized:{'1' * 64}:{str(execution) * 64}:{'3' * 64}",
            ),
            "execution_evidence": (),
            "identity_protocol": None,
        }
    )
    if catalog_root:
        from fundamental_service.dqc_rulesets import (
            DqcRulesetCatalogV1,
            DqcRulesetBindingV1,
        )

        catalog = DqcRulesetCatalogV1(
            bindings=(
                DqcRulesetBindingV1(
                    taxonomy_namespace="http://fasb.org/us-gaap/2025",
                    path=Path(catalog_root) / "rules.zip",
                    sha256="4" * 64,
                ),
            )
        )
        raw = raw.model_copy(
            update={
                "validation_profile": raw.validation_profile.model_copy(
                    update={"dqc_ruleset_catalog": catalog}
                )
            }
        )
    source = request.original.source
    if offset:
        source = source.model_copy(
            update={
                "captured_at": source.captured_at.astimezone(offset),
                "available_at": source.available_at.astimezone(offset),
            }
        )
    original = evaluate_original_issuer(
        raw, source=source, decision_at=request.original.decision_at
    )
    refs = tuple(
        ref.model_copy(
            update={
                "artifact_id": ref.artifact_id + f":execution-{execution}",
                "content_hash": str(execution) * 64,
            }
        )
        for ref in request.evidence_refs
    )
    integrity = request.integrity.model_copy(
        update={
            "validation_evidence": raw.validation_evidence,
            "captured_at": source.captured_at,
        }
    )
    return request.model_copy(
        update={"original": original, "integrity": integrity, "evidence_refs": refs}
    )


def test_reparse_has_distinct_exact_evidence_but_same_computation_and_mapping(tmp_path):
    request, store, _, _ = case(tmp_path)
    a, b = rebuilt(request, 1), rebuilt(request, 2)
    assert a.original.report.execution_evidence != b.original.report.execution_evidence
    assert a.original.report.replay_digest() == b.original.report.replay_digest()
    identities = MappingInputDigests()
    assert identities.input_digest(a) != identities.input_digest(b)
    assert mapping_computation_digest(
        a, automatic_mapping_policy_digest()
    ) == mapping_computation_digest(b, automatic_mapping_policy_digest())
    # Evaluate domain selection independently of storage admission. Exact action
    # proofs remain the responsibility of approve_mapping's storage boundary.
    a = a.model_copy(update={"evidence_refs": request.evidence_refs})
    b = b.model_copy(update={"evidence_refs": request.evidence_refs})
    first, second = evaluate(a, store), evaluate(b, store)
    assert first.status == second.status == "approved"
    assert first.mapping == second.mapping
    assert first.computation == second.computation
    assert first.input_digest != second.input_digest


@pytest.mark.parametrize("max_reports,max_bytes", ((0, 0), (1, 1), (1, 64 * 1024**2)))
def test_computation_context_eviction_changes_no_identity(
    tmp_path, max_reports, max_bytes
):
    request = rebuilt(case(tmp_path)[0], 1)
    scope = MappingInputDigests(max_reports=max_reports, max_bytes=max_bytes)
    expected = mapping_computation_digest(request, "a" * 64)
    for candidate in (request, rebuilt(request, 2), request):
        assert (
            mapping_computation_digest(candidate, "a" * 64, input_digests=scope)
            == expected
        )


@pytest.mark.parametrize("change", ("missing", "changed"))
def test_signed_computation_is_bound_to_exact_approval(tmp_path, change):
    from fundamental_service.automatic_mapping import verify_automatic_mapping_replay
    from fundamental_service.data_releases import (
        AutomaticMappingApprovalV1,
        DataReleaseError,
        sign_automatic_mapping_approval,
        verify_mapping_review_evidence,
    )
    from test_automatic_mapping import MACHINE_KEY, approve

    request, store, roots, _ = case(tmp_path)
    receipt = approve(request, store, roots)
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert approval.computation is not None
    changed = (
        None
        if change == "missing"
        else approval.computation.model_copy(update={"digest": "0" * 64})
    )
    unsigned = approval.model_copy(update={"computation": changed})
    with pytest.raises(DataReleaseError):
        verify_mapping_review_evidence(unsigned, roots)
    signed = sign_automatic_mapping_approval(
        unsigned.model_dump(exclude={"signature"}), MACHINE_KEY
    )
    verify_mapping_review_evidence(signed, roots)
    with pytest.raises(DataReleaseError, match="retained policy evaluation"):
        verify_automatic_mapping_replay(
            signed, evaluate(request, store).mapping, artifacts=store
        )


def test_catalog_root_and_equivalent_timezone_do_not_change_computation(tmp_path):
    request = case(tmp_path)[0]
    a = rebuilt(request, 1, catalog_root="/mount-a/dqc")
    b = rebuilt(
        request, 1, catalog_root="/mount-b/dqc", offset=timezone(timedelta(hours=8))
    )
    assert (
        a.original.report.validation_profile_digest
        == b.original.report.validation_profile_digest
    )
    assert a.original.report.validation_profile == b.original.report.validation_profile
    identities = MappingInputDigests()
    assert identities.input_digest(a) == identities.input_digest(b)
    assert mapping_computation_digest(a, "a" * 64) == mapping_computation_digest(
        b, "a" * 64
    )


@pytest.mark.parametrize(
    "change", ("text", "numeric", "severity", "finding", "policy", "source", "profile")
)
def test_computation_retains_full_facts_findings_and_dependencies(tmp_path, change):
    request = rebuilt(case(tmp_path)[0], 1)
    report = request.original.report
    before = parser_computation(report, "1" * 64)
    if change in {"text", "numeric"}:
        fact = report.facts[0].model_copy(
            update={"value": "changed disclosure" if change == "text" else "982323"}
        )
        changed = report.model_copy(update={"facts": (fact, *report.facts[1:])})
    elif change in {"severity", "finding"}:
        changed = report.model_copy(
            update={
                "findings": (
                    ArelleFindingV1(
                        code="audit",
                        severity="warning" if change == "severity" else "error",
                        message="complete evidence",
                    ),
                )
            }
        )
    elif change == "source":
        changed = report.model_copy(update={"source_content_hash": "f" * 64})
    elif change == "profile":
        changed = report.model_copy(update={"validation_profile_digest": "f" * 64})
    else:
        assert mapping_computation_digest(
            request, "a" * 64
        ) != mapping_computation_digest(request, "b" * 64)
        return
    assert sha256_digest(before) != sha256_digest(parser_computation(changed, "1" * 64))
