"""Synthetic release fixtures; these identities never authorize real evidence."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

from fundamental_service.contracts import (
    CanonicalFactV1,
    PeriodType,
    QualityStatus,
    SourceProvenanceV1,
    SourceRole,
    TraceV1,
    XbrlContextV1,
)
from fundamental_service.equity_award_evidence import EquityDilutionEvidenceV1
from fundamental_service.equity_dilution import (
    CommonShareQuoteV1,
    EquityAwardInventoryV1,
    RestrictedStockAwardV1,
    TreasuryStockPolicyV1,
)

QUOTE_BYTES = b'{"price":"10","synthetic-test-only":true}'


def award_evidence(snapshot):
    instant = datetime(2025, 12, 31, tzinfo=timezone.utc)
    available = datetime(2026, 2, 1, tzinfo=timezone.utc)
    source = max(snapshot.source_records, key=lambda item: item.available_at)
    facts = []
    for role, value, unit, currency in (
        ("equity_award_quantity", "10", "xbrli:shares", None),
        ("equity_award_unrecognized_compensation", "0", "iso4217:USD", "USD"),
    ):
        concept = "us-gaap:" + role
        facts.append(
            CanonicalFactV1(
                contract_version="fundamental.v1",
                fact_id=role + ":" + snapshot.snapshot_id,
                issuer_id=snapshot.identity.issuer_id,
                security_id=snapshot.identity.security_id,
                concept=concept,
                normalized_field=role,
                value=Decimal(value),
                unit=unit,
                scale=0,
                currency=currency,
                period_end=instant.date(),
                instant=instant.date(),
                context=XbrlContextV1(
                    concept_qname=concept,
                    period_type=PeriodType.INSTANT,
                    instant=instant.date(),
                    unit_qname=unit,
                    measure=unit,
                    entity_scope=snapshot.identity.issuer_id,
                    consolidation_scope="consolidated",
                    context_id=role,
                ),
                security_scope=snapshot.identity.security_id,
                as_of=instant,
                available_at=available,
                filed_at=available,
                captured_at=snapshot.valuation_timestamp,
                accession_number=source.accession_number or "0000000001-26-000001",
                filing_version="original",
                taxonomy_version="synthetic-us-gaap-2025",
                source=SourceProvenanceV1(
                    source_url=source.uri,
                    content_hash=source.content_hash,
                    source_role=SourceRole.FILING,
                    captured_at=snapshot.valuation_timestamp,
                    available_at=available,
                    filed_at=available,
                    accession_number=source.accession_number or "0000000001-26-000001",
                    parser_version=snapshot.parser_version,
                    terms_reference="synthetic-test-only",
                ),
                quality=QualityStatus.VERIFIED,
                mapping_decision_id="mapping-" + role,
                mapping_confidence="high",
            )
        )
    return EquityDilutionEvidenceV1(
        snapshot_manifest_digest=snapshot.manifest_digest,
        inventory=EquityAwardInventoryV1(
            issuer_id=snapshot.identity.issuer_id,
            security_id=snapshot.identity.security_id,
            currency="USD",
            period_end=instant.date(),
            complete_inventory=True,
            coverage_evidence=TraceV1(
                source_refs=(source.content_hash,),
                as_of=instant,
                available_at=available,
                captured_at=snapshot.valuation_timestamp,
                description="Synthetic award completeness test; no real review",
            ),
            instruments=(
                RestrictedStockAwardV1(
                    instrument_id="synthetic-rsu",
                    quantity=facts[0],
                    unrecognized_compensation=facts[1],
                ),
            ),
        ),
        quote=CommonShareQuoteV1(
            issuer_id=snapshot.identity.issuer_id,
            security_id=snapshot.identity.security_id,
            currency="USD",
            price=Decimal(10),
            source_id="synthetic-close",
            source_uri="https://example.invalid/synthetic-close",
            source_version="synthetic-v1",
            terms_reference="synthetic-test-only",
            content_hash=sha256(QUOTE_BYTES).hexdigest(),
            as_of=snapshot.valuation_timestamp - timedelta(days=1),
            available_at=snapshot.valuation_timestamp - timedelta(days=1),
            captured_at=snapshot.valuation_timestamp,
        ),
        policy=TreasuryStockPolicyV1(
            policy_version="synthetic-treasury-stock-v1",
            max_quote_age_seconds=3 * 86400,
        ),
    )
