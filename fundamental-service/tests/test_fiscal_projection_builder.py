from __future__ import annotations

import base64
import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import (
    ArtifactRefV1,
    AutomaticMappingEvaluatorV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerifierV1,
)
from fundamental_service.fiscal_candidate_contracts import (
    ClassifiedSourceForCandidateV1,
    FiscalCandidateClassificationBindingV1,
)
from fundamental_service.fiscal_discovery import FiscalDiscoveryEvidenceV1
from fundamental_service.fiscal_projection_builder import FiscalProjectionBuilder
from fundamental_service.fiscal_source_closure import FiscalSourceMetadataRead
from fundamental_service.fiscal_statement_mapping import (
    FISCAL_MAPPING_EVALUATOR_ID,
    FiscalMappingApprovalOwner,
    fiscal_mapping_policy_digest,
    map_fiscal_primary_source,
)
from fundamental_service.fiscal_statement_registry import (
    fiscal_primary_scopes,
    fiscal_reviewed_coverage,
    fiscal_statement_registry,
)
from fundamental_service.fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

FIXTURES = Path(__file__).parent / "fixtures/quarterly-statements"
RETAINED_REVISION = "293c068cc8cca6a4329b13a21f88ce93c1b47326"


class SyntheticDiscoveryPort:
    def __init__(self, evidence):
        self.evidence = evidence

    def read(self, identity, *, deadline_at):
        assert identity == self.evidence.artifact_id
        return self.evidence


class SyntheticRetainedSourcePort:
    def __init__(self, evidence, artifacts):
        self.evidence, self.artifacts = evidence, artifacts

    def read_with_metadata(self, identity, *, deadline_at):
        item = self.evidence[identity]
        if self.artifacts.get(identity).status != "valid":
            raise SnapshotError(
                "SYNTHETIC_SOURCE_REFUSED", "synthetic source closure is revoked"
            )
        return FiscalSourceMetadataRead(
            item, ((identity, self.artifacts.get(identity)),)
        )


class SyntheticClassificationPort:
    def __init__(self, bindings):
        self.bindings = {
            item.source_validation_ref.artifact_id: item for item in bindings
        }
        self.revoked = False

    def require_candidate_source(self, scope, classification_refs, *, deadline_at):
        binding = self.bindings[scope.source_validation_ref.artifact_id]
        if (
            self.revoked
            or scope.witness_ref != binding.witness_ref
            or classification_refs != binding.classification_refs
        ):
            raise SnapshotError(
                "SYNTHETIC_CLASSIFICATION_REFUSED", "test classification refused"
            )
        return ClassifiedSourceForCandidateV1(
            scope=scope, classification_refs=classification_refs
        )


def _ref(publication, role):
    record = publication.artifact
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def _retained_root():
    configured = os.getenv("ISSUE495_RETAINED_EVIDENCE_ROOT")
    if not configured:
        pytest.skip(
            "set ISSUE495_RETAINED_EVIDENCE_ROOT for retained original/source builder checks"
        )
    return Path(configured)


def _case(tmp_path, case_id, *, classifications=True, artifact_type=ArtifactStore):
    root = _retained_root()
    formal = root / "formal-fiscal-sources" / RETAINED_REVISION / case_id
    discovery_payload = json.loads(
        next(formal.glob("discover-*.stdout.json")).read_bytes()
    )
    discovery = FiscalDiscoveryEvidenceV1.model_validate_json(
        json.dumps(discovery_payload["evidence"])
    )
    artifacts = artifact_type(tmp_path / "artifacts")
    discovery_ref = _ref(
        artifacts.put_with_receipt(
            discovery.artifact_id, discovery, discovery.dependencies
        ),
        "fiscal-discovery",
    )
    case = json.loads((FIXTURES / "cases" / (case_id + ".json")).read_bytes())
    sources = {}
    bindings = []
    for filing in case["filings"]:
        payload = json.loads(
            next(
                formal.glob(filing["accession_number"] + "-*.stdout.json")
            ).read_bytes()
        )["evidence"]
        item = FiscalOriginalValidationEvidenceV1.model_validate_json(
            json.dumps(payload)
        )
        publication = artifacts.put_bytes_with_receipt(
            item.artifact_id,
            canonical_bytes(item.model_dump(mode="json")),
            item.dependencies,
            media_type="application/json",
        )
        sources[item.artifact_id] = item
        if isinstance(item.outcome, FiscalValidationCompleteRefusedV1):
            source_ref = _ref(publication, "fiscal-original-validation")
            witness = _ref(
                artifacts.put_with_receipt(
                    "synthetic-fixture-witness:" + case_id,
                    {"protocol": "synthetic-fixture-witness", "source": source_ref},
                ),
                "synthetic-fixture-witness",
            )
            classification = _ref(
                artifacts.put_with_receipt(
                    "synthetic-fixture-classification:" + case_id,
                    {
                        "protocol": "synthetic-fixture-classification",
                        "source": source_ref,
                        "witness": witness,
                    },
                ),
                "synthetic-fixture-classification",
            )
            bindings.append(
                FiscalCandidateClassificationBindingV1(
                    source_validation_ref=source_ref,
                    witness_ref=witness,
                    classification_refs=(classification,),
                )
            )
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    roots = DataReleaseTrustRootsV1(
        verifiers={
            "synthetic-fixture-verifier": DataReleaseVerifierV1(
                workflow_identity="synthetic-fixture",
                public_key_ed25519_base64=public,
                verification_suite_digest="0" * 64,
            )
        },
        automatic_mapping_evaluators={
            FISCAL_MAPPING_EVALUATOR_ID: AutomaticMappingEvaluatorV1(
                public_key_ed25519_base64=public,
                policy_digest=fiscal_mapping_policy_digest(),
            )
        },
    )
    approval_owner = FiscalMappingApprovalOwner(
        artifacts=artifacts, trust_roots=lambda: roots, private_key=lambda: key
    )
    preparer = _ref(
        artifacts.put_with_receipt(
            "synthetic-fixture-preparer:" + case_id,
            {"protocol": "synthetic-fixture-preparer", "case": case_id},
        ),
        "synthetic-fixture-preparer",
    )
    source_port = SyntheticRetainedSourcePort(sources, artifacts)
    classifier = (
        SyntheticClassificationPort(tuple(bindings)) if classifications else None
    )
    builder = FiscalProjectionBuilder(
        discovery=SyntheticDiscoveryPort(discovery),
        sources=source_port,
        artifacts=artifacts,
        content=FilesystemContentStore(root / "sources-worker/content"),
        pin=next(iter(sources.values())).request.pin,
        mapping_approvals=approval_owner,
        preparer_execution_ref=preparer,
        classifications=classifier,
    )
    return builder, discovery_ref, tuple(bindings), artifacts, sources


def _deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


@pytest.mark.parametrize(
    "case_id", ("aapl-historical", "aapl-current", "msft-historical", "msft-current")
)
def test_retained_primary_sources_produce_all_frozen_quarter_and_ttm_values(
    tmp_path, case_id
):
    builder, discovery_ref, bindings, _, _ = _case(tmp_path, case_id)
    actual = builder.prepare(
        discovery_ref,
        security_id="AAPL" if case_id.startswith("aapl") else "MSFT",
        classification_bindings=bindings,
        deadline_at=_deadline(),
    )
    projection = actual.projection
    by_frequency = {
        "quarter": {
            (target.period.end, node.row_id): node
            for index, target in enumerate(projection.quarter_periods)
            for node in projection.quarter_nodes[index * 25 : (index + 1) * 25]
        },
        "ttm": {
            (window.quarters[-1].period.end, node.row_id): node
            for index, window in enumerate(projection.ttm_windows)
            for node in projection.ttm_nodes[index * 25 : (index + 1) * 25]
        },
    }
    checked = 0
    for frequency, lookup in by_frequency.items():
        for path in sorted((FIXTURES / "golden" / frequency / case_id).glob("*.json")):
            for cell in json.loads(path.read_bytes()).get("cells", ()):
                node = lookup[(date.fromisoformat(cell["end_date"]), cell["row_id"])]
                assert node.value == (
                    Decimal(cell["value"]) if cell["value"] is not None else None
                ), (
                    case_id,
                    frequency,
                    cell["row_id"],
                    cell["end_date"],
                    node.reason_code,
                )
                availability = {
                    "missing": "unavailable",
                    "reported_with_derived_crosscheck": "reported",
                    "reported_instant": "reported",
                    "as_of_instant": "reported",
                    "boundary_instant": "reported",
                }.get(cell["availability"], cell["availability"])
                assert node.availability == availability
                if node.value is not None:
                    assert node.revision_basis_proof is not None
                    assert node.available_at <= actual.candidate.cutoff_at
                checked += 1
    assert checked == 325
    assert actual.candidate_publication.wrote
    assert all(
        not ref.artifact_id.startswith("synthetic-fixture:")
        for ref in actual.candidate.mapping_refs
    )
    assert projection.supported_history_threshold is None
    assert projection.valuation_eligibility == "not_evaluated"
    assert projection.quality is QualityStatus.PROVISIONAL
    if case_id.startswith("msft"):
        assert any(
            isinstance(item, ClassifiedSourceForCandidateV1)
            for item in actual.candidate.source_uses
        )
    again = builder.prepare(
        discovery_ref,
        security_id=actual.candidate.scope.security_id,
        classification_bindings=bindings,
        deadline_at=_deadline(),
    )
    assert not again.candidate_publication.wrote
    assert canonical_bytes(again.candidate) == canonical_bytes(actual.candidate)
    assert canonical_bytes(again.projection) == canonical_bytes(projection)
    retained = builder.verify_candidate(
        _ref(actual.candidate_publication, "fiscal-statement-candidate-v1"),
        deadline_at=_deadline(),
    )
    assert not retained.candidate_publication.wrote
    assert retained.candidate == actual.candidate


def test_raw_refused_source_cannot_form_candidate_without_classification_owner(
    tmp_path,
):
    builder, reference, _, artifacts, _ = _case(
        tmp_path, "msft-historical", classifications=False
    )
    with pytest.raises(SnapshotError) as caught:
        builder.prepare(reference, security_id="MSFT", deadline_at=_deadline())
    assert caught.value.code == "FISCAL_CLASSIFICATION_UNCONFIGURED"


def test_reviewed_registry_contains_source_positions_without_expected_amounts():
    registry = fiscal_statement_registry()
    sources = fiscal_primary_scopes(registry)
    assert len(sources) == 33
    assert len(fiscal_reviewed_coverage(registry)) == 4
    assert all(item.tables and item.disclosures for item in sources)
    assert all(
        "value" not in type(fact).model_fields
        and "canonical_decimal" not in type(fact).model_fields
        for source in sources
        for fact in source.facts
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_archive",
        "wrong_table",
        "wrong_context",
        "wrong_unit",
        "wrong_dimension",
        "wrong_raw_precision",
    ),
)
def test_primary_mapping_refuses_changed_source_scope(tmp_path, mutation):
    builder, _, _, _, sources = _case(tmp_path, "msft-historical")
    evidence = next(
        item
        for item in sources.values()
        if item.request.filing.accession_number == "0001564590-23-000733"
    )
    registry = fiscal_statement_registry()
    reviewed = next(
        item
        for item in fiscal_primary_scopes(registry)
        if item.accession_number == evidence.request.filing.accession_number
    )
    coverage = next(
        item
        for item in fiscal_reviewed_coverage(registry)
        if item.issuer_id == reviewed.issuer_id
        and item.quarters[-1].period.end == date(2024, 9, 30)
    )
    receipt = next(
        item
        for item in evidence.outcome.responses
        if item.uri == evidence.outcome.integrity.archive_uri
    )
    archive = builder.content.get(receipt.content_hash, media_type=receipt.media_type)
    reference = ArtifactRefV1(
        role="fiscal-original-validation",
        artifact_id=evidence.artifact_id,
        content_hash=sha256_digest(evidence.model_dump(mode="json")),
        media_type="application/json",
    )
    if mutation == "wrong_archive":
        archive = archive[:-1] + bytes((archive[-1] ^ 1,))
    elif mutation in {"wrong_table", "wrong_context", "wrong_unit"}:
        first = reviewed.facts[0]
        change = {
            "wrong_table": {"table_index": first.table_index + 1},
            "wrong_context": {"context_id": "unreviewed"},
            "wrong_unit": {"unit": "xbrli:shares"},
        }[mutation]
        reviewed = reviewed.model_copy(
            update={"facts": (first.model_copy(update=change), *reviewed.facts[1:])}
        )
    else:
        report = evidence.outcome.claim.report
        target = reviewed.facts[0]
        changed = tuple(
            fact.model_copy(
                update={"dimensions": (("unreviewed:Axis", "unreviewed:Member"),)}
                if mutation == "wrong_dimension"
                else {"decimals": "0"}
            )
            if fact.concept == target.concept and fact.context_id == target.context_id
            else fact
            for fact in report.facts
        )
        evidence = evidence.model_copy(
            update={
                "outcome": evidence.outcome.model_copy(
                    update={
                        "claim": evidence.outcome.claim.model_copy(
                            update={
                                "report": report.model_copy(update={"facts": changed})
                            }
                        )
                    }
                )
            }
        )
        reference = reference.model_copy(
            update={"content_hash": sha256_digest(evidence.model_dump(mode="json"))}
        )
    with pytest.raises(SnapshotError):
        map_fiscal_primary_source(
            evidence,
            reference,
            archive=archive,
            reviewed=reviewed,
            target_periods=tuple(item.period for item in coverage.quarters),
            security_id="MSFT",
            policy_digest=fiscal_mapping_policy_digest(),
            check_deadline=lambda: 60.0,
        )


def test_preparation_refuses_unconfigured_mapping_authority_before_source_work(
    tmp_path,
):
    builder, reference, _, _, _ = _case(tmp_path, "aapl-historical")
    builder.mapping_approvals = None
    with pytest.raises(SnapshotError) as caught:
        builder.prepare(reference, security_id="AAPL", deadline_at=_deadline())
    assert caught.value.code == "FISCAL_MAPPING_AUTHORITY_UNCONFIGURED"


def test_security_from_another_issuer_cannot_name_a_candidate(tmp_path):
    builder, reference, _, _, _ = _case(tmp_path, "aapl-historical")
    with pytest.raises(SnapshotError) as caught:
        builder.prepare(reference, security_id="MSFT", deadline_at=_deadline())
    assert caught.value.code == "FISCAL_PROJECTION_SOURCE_INVALID"


def test_source_revoked_during_candidate_publication_refuses_and_retry_stays_refused(
    tmp_path,
):
    class RevokingStore(ArtifactStore):
        source_identity = None

        def put_with_receipt(self, artifact_id, *args, **kwargs):
            result = super().put_with_receipt(artifact_id, *args, **kwargs)
            if (
                artifact_id.startswith("fiscal-statement-candidate-v1:")
                and self.source_identity is not None
            ):
                self.invalidate(self.source_identity)
            return result

    builder, reference, bindings, artifacts, sources = _case(
        tmp_path, "aapl-historical", artifact_type=RevokingStore
    )
    artifacts.source_identity = next(iter(sources))
    with pytest.raises(SnapshotError):
        builder.prepare(
            reference,
            security_id="AAPL",
            classification_bindings=bindings,
            deadline_at=_deadline(),
        )
    with pytest.raises(SnapshotError):
        builder.prepare(
            reference,
            security_id="AAPL",
            classification_bindings=bindings,
            deadline_at=_deadline(),
        )


def test_candidate_verification_never_publishes_or_signs(tmp_path):
    builder, reference, bindings, artifacts, _ = _case(tmp_path, "aapl-historical")
    result = builder.prepare(
        reference,
        security_id="AAPL",
        classification_bindings=bindings,
        deadline_at=_deadline(),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("read attempted publication or signing")

    artifacts.put_with_receipt = forbidden
    builder.mapping_approvals.private_key = forbidden
    retained = builder.verify_candidate(
        _ref(result.candidate_publication, "fiscal-statement-candidate-v1"),
        deadline_at=_deadline(),
    )
    assert retained.candidate == result.candidate


def test_wrong_fiscal_year_start_has_no_primary_ytd_proof(tmp_path, monkeypatch):
    import fundamental_service.fiscal_statement_registry as implementation

    builder, reference, bindings, _, _ = _case(tmp_path, "msft-historical")
    original = implementation.fiscal_reviewed_coverage

    def changed(registry):
        values = []
        for coverage in original(registry):
            if coverage.issuer_id == "0000789019" and coverage.quarters[
                -1
            ].period.end == date(2024, 9, 30):
                first = coverage.quarters[0]
                first = first.model_copy(
                    update={
                        "period": first.period.model_copy(
                            update={"fiscal_year_start": first.period.start}
                        )
                    }
                )
                coverage = coverage.model_copy(
                    update={"quarters": (first, *coverage.quarters[1:])}
                )
            values.append(coverage)
        return tuple(values)

    monkeypatch.setattr(implementation, "fiscal_reviewed_coverage", changed)
    with pytest.raises(SnapshotError):
        builder.prepare(
            reference,
            security_id="MSFT",
            classification_bindings=bindings,
            deadline_at=_deadline(),
        )
