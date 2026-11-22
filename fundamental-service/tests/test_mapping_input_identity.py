"""Shared canonical fragments preserve existing mapping/signature identities."""

from datetime import timedelta, timezone

import pytest

from fundamental_service import mapping_input_identity as identity
from fundamental_service.contracts import IdentityV1
from fundamental_service.mapping_input_identity import MappingInputDigests
from fundamental_service.serialization import sha256_digest
from fundamental_service.arelle_parser import fact_semantic_digest
from test_automatic_mapping import case
from test_automatic_mapping_batch import batch_case


@pytest.mark.parametrize("batch", (False, True))
def test_fragment_identity_matches_the_complete_existing_wire_contract(tmp_path, batch):
    request = (batch_case if batch else case)(tmp_path)[0]
    checks = MappingInputDigests()
    assert checks.original_digest(request.original) == sha256_digest(request.original)
    assert checks.input_digest(request) == sha256_digest(request)
    assert checks.report_content_digest(request.original.report) == sha256_digest(
        request.original.report.model_dump(mode="json")
    )


@pytest.mark.parametrize(
    "change",
    (
        "revision",
        "evaluator",
        "integrity",
        "references",
        "security",
        "proposal",
        "header",
        "report",
    ),
)
def test_every_input_field_and_original_claim_keeps_its_existing_identity(
    tmp_path, change
):
    request = case(tmp_path)[0]
    checks = MappingInputDigests()
    before = checks.input_digest(request)
    updates = {
        "revision": {"source_revision": "f" * 40},
        "evaluator": {"evaluator_id": "different-evaluator"},
        "integrity": {
            "integrity": request.integrity.model_copy(
                update={"raw_content_hash": "f" * 64}
            )
        },
        "references": {"evidence_refs": tuple(reversed(request.evidence_refs))},
        "security": {
            "security_identity": request.security_identity.model_copy(
                update={"security_id": "OTHER"}
            )
        }
        if request.security_identity is not None
        else {
            "security_identity": IdentityV1(
                issuer_id=request.original.source.cik,
                issuer_name="Test issuer",
                domicile="US",
                reporting_basis="us-gaap",
                security_id="OTHER",
                share_class="common",
                currency="USD",
            )
        },
        "proposal": {
            "proposal": request.proposal.model_copy(
                update={"normalized_field": "unsupported"}
            )
        },
        "header": {
            "original": request.original.model_copy(
                update={
                    "decision_at": request.original.decision_at + timedelta(seconds=1)
                }
            )
        },
        "report": {
            "original": request.original.model_copy(
                update={
                    "report": request.original.report.model_copy(
                        update={"validation_evidence": ("changed",)}
                    )
                }
            )
        },
    }
    changed = request.model_copy(update=updates[change])
    assert checks.input_digest(changed) == sha256_digest(changed) != before
    assert checks.input_digest(request) == before


def test_original_headers_and_report_serializer_keep_distinct_timestamp_rules(tmp_path):
    request = case(tmp_path)[0]
    offset = timezone(timedelta(hours=8))
    original = request.original.model_copy(
        update={
            "decision_at": request.original.decision_at.astimezone(offset),
            "report": request.original.report.model_copy(
                update={
                    "parsed_at": request.original.report.parsed_at.astimezone(offset),
                }
            ),
        }
    )
    request = request.model_copy(update={"original": original})
    checks = MappingInputDigests()
    # Original timestamps use fundamental-json-v1 UTC; the report's explicit
    # JSON field serializer preserves its own timestamp representation.
    assert checks.original_digest(original) == sha256_digest(original)
    assert checks.input_digest(request) == sha256_digest(request)


def test_many_mapping_inputs_serialize_their_shared_report_once(tmp_path, monkeypatch):
    request = case(tmp_path)[0]
    serialize = identity.canonical_bytes
    reports = []

    def observed(value):
        if isinstance(value, dict) and "facts" in value and "filing_path" in value:
            reports.append(True)
        return serialize(value)

    monkeypatch.setattr(identity, "canonical_bytes", observed)
    checks = MappingInputDigests()
    for index in range(5):
        changed = request.model_copy(update={"evaluator_id": f"evaluator-{index}"})
        assert checks.input_digest(changed) == sha256_digest(changed)
        assert checks.original_digest(changed.original) == sha256_digest(
            changed.original
        )
        assert checks.input_digest(changed) == sha256_digest(changed)
    assert len(reports) == 1
    copied = request.model_copy(
        update={
            "original": request.original.model_copy(
                update={"report": request.original.report.model_copy()}
            )
        }
    )
    assert checks.input_digest(copied) == sha256_digest(request)
    assert len(reports) == 2
    assert MappingInputDigests().input_digest(request) == sha256_digest(request)
    assert len(reports) == 3


def test_accounting_observation_index_preserves_ids_and_retention_budget(tmp_path):
    request = case(tmp_path)[0]
    report = request.original.report
    checks = MappingInputDigests()
    observed = checks.report_facts(report)
    assert dict(observed) == {sha256_digest(fact): fact for fact in report.facts}
    assert checks.report_facts(report) is observed
    assert checks.report_fact_digest(report) == identity.fact_semantic_digest(report)
    with pytest.raises(TypeError):
        observed["0" * 64] = report.facts[0]
    # A replacement is a new input, even if its claimed source identity matches.
    changed = report.model_copy(update={"facts": report.facts[:-1]})
    assert checks.report_fact_digest(changed) != checks.report_fact_digest(report)
    tiny = MappingInputDigests(max_bytes=1)
    assert dict(tiny.report_facts(report)) == dict(observed)
    assert tiny.report_facts(report) is not tiny.report_facts(report)
    assert tiny._size <= tiny._max_bytes and not tiny._reports


@pytest.mark.parametrize(
    "limits", ({}, {"max_bytes": 0}, {"max_reports": 0}, {"max_bytes": 1})
)
@pytest.mark.parametrize("offset", (0, 8))
@pytest.mark.parametrize("reverse", (False, True))
def test_all_lazy_identities_preserve_full_wire_bytes_with_duplicates_and_budgets(
    tmp_path, limits, offset, reverse
):
    report = case(tmp_path)[0].original.report
    facts = (*report.facts, report.facts[0], report.facts[-1])
    if reverse:
        facts = tuple(reversed(facts))
    report = report.model_copy(
        update={
            "facts": facts,
            "parsed_at": report.parsed_at.astimezone(timezone(timedelta(hours=offset))),
            "execution_evidence": ("test-execution-proof",),
        }
    )
    full = report.model_dump(mode="json")
    semantic = {
        "fact_count": len(facts),
        "facts": sorted(full["facts"], key=sha256_digest),
    }
    replay = {
        name: full[name]
        for name in (
            "parser_version",
            "taxonomy_version",
            "validation_profile_digest",
            "source_content_hash",
            "taxonomy_cache_hash",
            "validation_engines",
            "validation_evidence",
            "offline",
            "network_attempt_count",
        )
    }
    replay.update(
        facts=semantic["facts"], findings=sorted(full["findings"], key=sha256_digest)
    )
    computation = {
        key: value for key, value in full.items() if key != "execution_evidence"
    }
    computation["parsed_at"] = report.parsed_at
    checks = MappingInputDigests(**limits)
    for _ in range(2):
        assert checks.report_content_digest(report) == sha256_digest(full)
        assert (
            checks.report_replay_digest(report)
            == sha256_digest(replay)
            == report.replay_digest()
        )
        assert (
            checks.report_fact_digest(report)
            == sha256_digest(semantic)
            == fact_semantic_digest(report)
        )
        assert checks.report_computation_digest(report) == sha256_digest(computation)
        assert dict(checks.report_facts(report)) == {sha256_digest(f): f for f in facts}
