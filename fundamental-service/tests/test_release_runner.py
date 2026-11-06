import base64
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.contracts import (
    CanonicalFactV1,
    IdentityV1,
    PeriodType,
    QualityStatus,
    SourceProvenanceV1,
    SourceRecordV1,
    SourceRole,
    SourceSnapshotV1,
    XbrlContextV1,
)
from fundamental_service.data_releases import (
    REQUIRED_DATA_RELEASE_GATES,
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    FactRefV1,
    MappingRefV1,
    SnapshotRefV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1, canonical_fact_digest
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import sha256_digest


class _Snapshots:
    def __init__(self, snapshot: SourceSnapshotV1) -> None:
        self.snapshot = snapshot

    def get(self, snapshot_id: str) -> SourceSnapshotV1:
        assert snapshot_id == self.snapshot.snapshot_id
        return self.snapshot


class _Facts:
    def __init__(self, fact: CanonicalFactV1) -> None:
        self.fact = fact

    def resolve(self, *, snapshot, valuation_timestamp, required_fields):
        _ = snapshot, valuation_timestamp
        assert required_fields == (self.fact.normalized_field,)
        return (self.fact,)


class _Mappings:
    def __init__(self, mapping: CanonicalMappingV1) -> None:
        self.mapping = mapping

    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1:
        assert mapping_id == self.mapping.decision_id
        return self.mapping


class _Artifacts:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self, artifact_id: str) -> bytes:
        assert artifact_id == "release-evidence"
        return self.content


def _fact() -> CanonicalFactV1:
    available = datetime(2026, 1, 1, tzinfo=UTC)
    period_start = datetime(2025, 1, 1).date()
    period_end = datetime(2025, 12, 31).date()
    return CanonicalFactV1(
        contract_version="fundamental.v1",
        fact_id="fact-revenue",
        issuer_id="CIK1",
        security_id="COMMON",
        concept="us-gaap:Revenues",
        normalized_field="revenue",
        value=Decimal(100),
        unit="USD",
        scale=0,
        currency="USD",
        period_start=period_start,
        period_end=period_end,
        context=XbrlContextV1(
            concept_qname="us-gaap:Revenues",
            period_type=PeriodType.DURATION,
            start_date=period_start,
            end_date=period_end,
            unit_qname="iso4217:USD",
            measure="iso4217:USD",
            entity_scope="consolidated",
            consolidation_scope="consolidated",
            context_id="ctx-revenue",
        ),
        security_scope="COMMON",
        as_of=available,
        available_at=available,
        filed_at=available,
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
        accession_number="0000000001-25-000001",
        filing_version="original",
        taxonomy_version="us-gaap-2025",
        source=SourceProvenanceV1(
            source_url="https://www.sec.gov/Archives/fixture.htm",
            content_hash="a" * 64,
            source_role=SourceRole.FILING,
            captured_at=datetime(2026, 1, 2, tzinfo=UTC),
            available_at=available,
            filed_at=available,
            accession_number="0000000001-25-000001",
            parser_version="arelle-2.47.4",
            taxonomy_version="us-gaap-2025",
            terms_reference="SEC fair access policy",
        ),
        quality=QualityStatus.VERIFIED,
    )


def _candidate() -> (
    tuple[
        DataReleaseManifestV1,
        object,
        _Snapshots,
        _Facts,
        _Mappings,
        _Artifacts,
        DataReleaseTrustRootsV1,
    ]
):
    fact = _fact()
    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="mapping-revenue",
        source_concept="us-gaap:Revenues",
        normalized_field="revenue",
        mapping_version="mapping-v1",
        confidence="high",
        reviewer="independent-reviewer",
        reviewed_at=datetime(2026, 1, 2, tzinfo=UTC),
        status="approved",
    )
    snapshot_payload = {
        "contract_version": "fundamental.v1",
        "snapshot_id": "snapshot-release",
        "identity": IdentityV1(
            issuer_id="CIK1",
            issuer_name="Example Corp",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="COMMON",
            share_class="common",
            currency="USD",
        ),
        "valuation_timestamp": datetime(2026, 1, 3, tzinfo=UTC),
        "captured_at": datetime(2026, 1, 2, tzinfo=UTC),
        "source_records": (
            SourceRecordV1(
                source_id="filing",
                uri="https://www.sec.gov/Archives/fixture.htm",
                role=SourceRole.FILING,
                available_at=datetime(2026, 1, 1, tzinfo=UTC),
                captured_at=datetime(2026, 1, 2, tzinfo=UTC),
                http_status=200,
                media_type="text/html",
                terms_reference="SEC fair access policy",
                content_hash="a" * 64,
                parser_version="arelle-2.47.4",
            ),
        ),
        "parser_version": "arelle-2.47.4",
        "policy_version": "policy-v1",
        "coverage_status": QualityStatus.VERIFIED,
    }
    provisional = SourceSnapshotV1.model_construct(
        **snapshot_payload,
        manifest_digest="0" * 64,
    )
    snapshot = SourceSnapshotV1(
        **snapshot_payload,
        manifest_digest=sha256_digest(
            provisional.model_dump(exclude={"manifest_digest", "snapshot_id"})
        ),
    )
    fact_ref = FactRefV1(
        fact_id=fact.fact_id, fact_digest=sha256_digest(fact.model_dump(mode="json"))
    )
    snapshot_ref = SnapshotRefV1(
        snapshot_id=snapshot.snapshot_id,
        manifest_digest=snapshot.manifest_digest,
        facts=(fact_ref,),
        fact_set_digest=sha256_digest((fact_ref,)),
    )
    artifact_content = b"release-evidence-v1"
    artifact_ref = ArtifactRefV1(
        artifact_id="release-evidence",
        content_hash=hashlib.sha256(artifact_content).hexdigest(),
        media_type="application/json",
        role="quality-evidence",
    )
    payload = {
        "profile_id": "sec-public-pit-v1",
        "release_id": "release-canary",
        "created_at": datetime(2026, 1, 3, tzinfo=UTC),
        "snapshot_refs": (snapshot_ref,),
        "mapping_refs": (
            MappingRefV1(
                mapping_id=mapping.decision_id,
                mapping_digest=sha256_digest(mapping.model_dump(mode="json")),
            ),
        ),
        "taxonomy_refs": (artifact_ref,),
        "parser_version": "arelle-2.47.4",
        "quality_profile_digest": "c" * 64,
        "required_fields": ("revenue",),
        "artifact_refs": (artifact_ref,),
    }
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    reviewer_key = Ed25519PrivateKey.from_private_bytes(b"reviewer-key".ljust(32, b"0"))
    review = sign_mapping_review_evidence(
        {
            "mapping_id": mapping.decision_id,
            "mapping_digest": payload["mapping_refs"][0].mapping_digest,
            "author_id": "mapping-builder",
            "reviewer_id": "mapping-reviewer",
            "reviewed_at": datetime(2026, 1, 3, tzinfo=UTC),
            "evidence_refs": (artifact_ref,),
            "fixture_digest": sha256_digest({"fixture": "revenue"}),
        },
        reviewer_key,
    )
    verifier_key = Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0"))
    verification = sign_data_release_verification(
        {
            "manifest_digest": manifest.manifest_digest,
            "verification_suite_digest": "d" * 64,
            "source_revision": "1" * 40,
            "verification_run_id": "canary-test-run",
            "workflow_identity": "local://release-canary",
            "verifier_id": "canary-verifier",
            "passed_gate_ids": tuple(sorted(REQUIRED_DATA_RELEASE_GATES)),
            "evidence_refs": (artifact_ref,),
            "mapping_reviews": (review,),
        },
        verifier_key,
    )
    trust_roots = DataReleaseTrustRootsV1(
        verifiers={
            "canary-verifier": {
                "workflow_identity": "local://release-canary",
                "public_key_ed25519_base64": base64.b64encode(
                    verifier_key.public_key().public_bytes_raw()
                ).decode(),
                "verification_suite_digest": "d" * 64,
            }
        },
        mapping_reviewers={
            "mapping-reviewer": base64.b64encode(
                reviewer_key.public_key().public_bytes_raw()
            ).decode()
        },
    )
    return (
        manifest,
        verification,
        _Snapshots(snapshot),
        _Facts(fact),
        _Mappings(mapping),
        _Artifacts(artifact_content),
        trust_roots,
    )


def test_release_canary_replays_exact_digests_without_activation() -> None:
    manifest, verification, snapshots, facts, mappings, artifacts, roots = _candidate()
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )

    first = runner.validate(manifest, verification)
    second = runner.validate(manifest, verification)

    assert first.canary_digest == second.canary_digest
    assert first.candidate_manifest_digest == manifest.manifest_digest
    assert first.checked_snapshot_ids == ("snapshot-release",)
    assert len(first.checked_fact_digests) == 1


def test_release_canary_ignores_point_in_time_selection_annotations() -> None:
    manifest, verification, snapshots, facts, mappings, artifacts, roots = _candidate()
    facts.fact = facts.fact.model_copy(
        update={
            "rejected_candidates": ("fact-older",),
            "point_in_time_policy": "pit-v1",
            "selection_reason": "latest_available_after_fact_key_point_in_time_selection",
        }
    )
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )

    report = runner.validate(manifest, verification)

    assert report.checked_fact_digests == (canonical_fact_digest(facts.fact),)


def test_release_canary_blocks_artifact_hash_mismatch() -> None:
    manifest, verification, snapshots, facts, mappings, artifacts, roots = _candidate()
    artifacts.content = b"tampered"
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )

    with pytest.raises(DataReleaseError, match="failed hash verification") as error:
        runner.validate(manifest, verification)
    assert error.value.code == "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"


def test_release_canary_blocks_point_in_time_fact_mismatch() -> None:
    manifest, verification, snapshots, facts, mappings, artifacts, roots = _candidate()
    facts.fact = facts.fact.model_copy(update={"value": Decimal(101)})
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )

    with pytest.raises(DataReleaseError) as error:
        runner.validate(manifest, verification)
    assert error.value.code == "DATA_RELEASE_FACT_MISMATCH"
