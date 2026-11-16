"""Shared canonical fragments preserve existing mapping/signature identities."""

from datetime import timedelta, timezone

import pytest

from fundamental_service import mapping_input_identity as identity
from fundamental_service.contracts import IdentityV1
from fundamental_service.mapping_input_identity import MappingInputDigests
from fundamental_service.serialization import sha256_digest
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
