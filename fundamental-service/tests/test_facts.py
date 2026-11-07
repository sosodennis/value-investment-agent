from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fundamental_service.contracts import (
    DimensionV1,
    IdentityV1,
    QualityStatus,
    SourceProvenanceV1,
    SourceRecordV1,
    SourceRole,
    SourceSnapshotV1,
)
from fundamental_service.facts import (
    CanonicalMappingV1,
    FactCandidateV1,
    PinnedValidationProfile,
    TaxonomyManifestV1,
    TaxonomyPackageV1,
    ValidationFindingV1,
    quality_gate,
    resolve_canonical_facts,
    select_fact,
)
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import SnapshotError


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


def snapshot_for_facts() -> SourceSnapshotV1:
    available = datetime(2025, 12, 1, tzinfo=timezone.utc)
    captured = datetime(2026, 1, 2, tzinfo=timezone.utc)
    identity = IdentityV1(
        issuer_id="CIK1",
        issuer_name="Example Co",
        domicile="US",
        reporting_basis="us-gaap",
        security_id="COMMON",
        share_class="COMMON",
        currency="USD",
    )
    source_record = SourceRecordV1(
        source_id="sec-filing",
        uri="https://example.test/10-k",
        role=SourceRole.FILING,
        available_at=available,
        captured_at=captured,
        http_status=200,
        media_type="text/html",
        terms_reference="sec-public",
        content_hash="a" * 64,
        parser_version="fixture-parser-v1",
        accession_number="0001-25-1",
    )
    payload = {
        "contract_version": "fundamental.v1",
        "snapshot_id": "snapshot-facts",
        "identity": identity,
        "valuation_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "captured_at": captured,
        "source_records": (source_record,),
        "parser_version": "fixture-parser-v1",
        "policy_version": "pit-v1",
        "coverage_status": QualityStatus.VERIFIED,
        "issues": (),
    }
    unchecked = SourceSnapshotV1.model_construct(**payload, manifest_digest="0" * 64)
    return SourceSnapshotV1(
        **payload,
        manifest_digest=sha256_digest(
            unchecked.model_dump(exclude={"manifest_digest", "snapshot_id"})
        ),
    )


def canonical(candidate_value: FactCandidateV1):
    return candidate_value.canonical_fact(quality=QualityStatus.VERIFIED)


def resolve(*facts):
    snapshot = snapshot_for_facts()
    return resolve_canonical_facts(
        facts,
        snapshot=snapshot,
        valuation_timestamp=snapshot.valuation_timestamp,
        required_fields=("revenue",),
    )


def test_field_resolution_prefers_dimensionless_consolidated_fact():
    total = canonical(candidate("total", "100", "2025-12-01", 2))
    segment = canonical(
        candidate("segment", "40", "2025-12-01", 2).model_copy(
            update={
                "dimensions": (
                    DimensionV1(name="us-gaap:ProductOrServiceAxis", member="Cloud"),
                ),
                "entity_scope": "segment",
                "consolidation_scope": "segmented",
            }
        )
    )

    selected = resolve(total, segment)

    assert selected[0].fact_id == "total"
    assert selected[0].value == Decimal("100")
    assert selected[0].rejected_candidate_reasons[0].candidate_id == "segment"
    assert (
        selected[0].rejected_candidate_reasons[0].reason
        == "non_consolidated_or_dimensional_candidate"
    )


def test_field_resolution_prefers_longest_duration_for_same_period_end():
    annual = canonical(
        candidate("annual", "100", "2025-12-01", 2).model_copy(
            update={"period_start": datetime(2025, 1, 1).date()}
        )
    )
    quarter = canonical(
        candidate("quarter", "30", "2025-12-01", 2).model_copy(
            update={"period_start": datetime(2025, 10, 1).date()}
        )
    )

    selected = resolve(annual, quarter)

    assert selected[0].fact_id == "annual"
    assert selected[0].value == Decimal("100")


def test_field_resolution_fails_closed_for_disagreeing_consolidated_totals():
    first = canonical(candidate("first-total", "100", "2025-12-01", 2))
    second = canonical(candidate("second-total", "101", "2025-12-01", 2))

    with pytest.raises(SnapshotError) as error:
        resolve(first, second)
    assert error.value.code == "FACT_CONFLICT"


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
    assert result.rejected_candidate_ids == ("future", "old")
    assert {item.candidate_id for item in result.rejected_candidate_reasons} == {
        "future",
        "old",
    }


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


def test_eligible_amendment_without_scope_abstains():
    result = select_fact(
        (
            candidate("original", "100", "2025-12-01", 2),
            candidate(
                "amendment",
                "101",
                "2025-12-20",
                2,
                is_amendment=True,
                amendment_scope="unknown",
            ),
        ),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.fact is None
    assert result.issues[0].code == "FACT_AMENDMENT_SCOPE_UNKNOWN"
    assert result.issues[0].severity == "fatal"


def test_unrelated_amendment_cannot_replace_original_fact():
    result = select_fact(
        (
            candidate("original", "100", "2025-12-01", 2),
            candidate(
                "amendment",
                "101",
                "2025-12-20",
                2,
                is_amendment=True,
                amendment_scope="unrelated",
            ),
        ),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert result.fact is not None
    assert result.fact.fact_id == "original"
    assert result.rejected_candidate_reasons[0].reason == (
        "unrelated_amendment_cannot_supersede_fact"
    )


def test_relevant_later_amendment_wins_and_records_original():
    original = candidate("original", "100", "2025-12-01", 2)
    amended_source = source().model_copy(
        update={
            "content_hash": "b" * 64,
            "accession_number": "0001-25-2",
        }
    )
    amendment = candidate("amendment", "101", "2025-12-20", 2).model_copy(
        update={
            "source": amended_source,
            "accession_number": "0001-25-2",
            "filing_version": "0001-25-2-amendment",
            "is_amendment": True,
            "amends_accession": "0001-25-1",
            "amendment_scope": "valuation_relevant",
        }
    )
    result = select_fact(
        (original, amendment), datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert result.fact is not None
    assert result.fact.fact_id == "amendment"
    assert result.rejected_candidate_ids == ("original",)


def test_equal_precision_conflict_across_filings_abstains():
    first = candidate("first", "100", "2025-12-01", 2)
    second = candidate("second", "101", "2025-12-01", 2).model_copy(
        update={
            "source": source().model_copy(
                update={
                    "content_hash": "b" * 64,
                    "accession_number": "0001-25-2",
                }
            ),
            "accession_number": "0001-25-2",
            "filing_version": "0001-25-2",
        }
    )
    result = select_fact((first, second), datetime(2026, 1, 1, tzinfo=timezone.utc))
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
