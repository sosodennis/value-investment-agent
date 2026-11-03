from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fundamental_service.contracts import SourceProvenanceV1, SourceRole
from fundamental_service.facts import (
    CanonicalMappingV1,
    FactCandidateV1,
    PinnedValidationProfile,
    TaxonomyManifestV1,
    TaxonomyPackageV1,
    ValidationFindingV1,
    quality_gate,
    select_fact,
)


def source() -> SourceProvenanceV1:
    return SourceProvenanceV1(
        source_url="https://example.test/10-k",
        content_hash="a" * 64,
        source_role=SourceRole.FILING,
        captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        available_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        filed_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        accession_number="0001-25-1",
        parser_version="fixture-parser-v1",
    )


def candidate(
    candidate_id: str, value: str, available: str, decimals: int, **kwargs
) -> FactCandidateV1:
    return FactCandidateV1(
        candidate_id=candidate_id,
        issuer_id="CIK1",
        security_id="COMMON",
        concept=kwargs.get("concept", "us-gaap:Revenues"),
        normalized_field="revenue",
        value=Decimal(value),
        unit="USD",
        scale=0,
        currency="USD",
        period_type="duration",
        period_start=datetime(2025, 1, 1).date(),
        period_end=datetime(2025, 12, 31).date(),
        dimensions=(),
        entity_scope="consolidated",
        consolidation_scope="consolidated",
        security_scope="COMMON",
        as_of=datetime(2025, 12, 31, tzinfo=timezone.utc),
        available_at=datetime.fromisoformat(available).replace(tzinfo=timezone.utc),
        filed_at=datetime.fromisoformat(available).replace(tzinfo=timezone.utc),
        captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        accession_number="0001-25-1",
        filing_version="original",
        decimals=decimals,
        context_id=candidate_id,
        unit_qname="xbrli:shares",
        measure="iso4217:USD",
        source=source(),
        taxonomy_version="us-gaap-2025",
        **{key: value for key, value in kwargs.items() if key != "concept"},
    )


def test_point_in_time_selection_prefers_latest_available_and_precision():
    result = select_fact(
        (
            candidate("old", "90", "2025-12-01", 0),
            candidate("precise", "100", "2025-12-15", 2),
            candidate("future", "999", "2026-02-01", 9),
        ),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.fact is not None
    assert result.fact.value == Decimal("100")
    assert result.rejected_candidate_ids == ("future",)


def test_equally_precise_conflict_blocks_fact():
    result = select_fact(
        (
            candidate("a", "100", "2025-12-15", 2),
            candidate("b", "101", "2025-12-15", 2),
        ),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.fact is None
    assert result.issues[0].code == "FACT_CONFLICT"


def test_missing_mapping_is_provisional_instead_of_verified():
    result = select_fact(
        (candidate("unmapped", "100", "2025-12-15", 2),),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.fact is not None
    assert result.fact.quality == "provisional"
    assert result.issues[0].code == "MAPPING_UNRESOLVED"


def test_source_provenance_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="captured_at"):
        SourceProvenanceV1(
            source_url="https://example.test/10-k",
            content_hash="a" * 64,
            source_role=SourceRole.FILING,
            captured_at=datetime(2026, 1, 2),
            available_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
            parser_version="fixture-parser-v1",
        )


def test_extension_mapping_requires_review_evidence():
    with pytest.raises(ValueError):
        CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id="map-1",
            source_concept="issuer:CustomRevenue",
            normalized_field="revenue",
            mapping_version="mapping-v1",
            confidence="high",
            status="approved",
        )


def test_pinned_profile_and_quality_gate():
    profile = PinnedValidationProfile(profile_hash="a" * 64)
    TaxonomyManifestV1(
        contract_version="fundamental.v1",
        manifest_id="dts-1",
        packages=(
            TaxonomyPackageV1(
                package_id="us-gaap",
                taxonomy_version="2025",
                effective_from=datetime(2025, 1, 1).date(),
                content_hash="b" * 64,
                validation_profile=profile,
            ),
        ),
        dts_hash="c" * 64,
        parser_version="arelle-2.47.4",
    )
    assert quality_gate(findings=(), mappings=()) == "verified"
    assert (
        quality_gate(
            findings=(
                ValidationFindingV1(
                    code="DQC_ERROR",
                    severity="error",
                    message="bad accounting fact",
                    rule_version="v31.0.3",
                    blocks_verified=True,
                ),
            ),
            mappings=(),
        )
        == "abstain"
    )
