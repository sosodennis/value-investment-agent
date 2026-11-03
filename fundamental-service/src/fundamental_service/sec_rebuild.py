"""Offline rebuild from captured SEC/XBRL bytes to canonical facts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .arelle_parser import ArelleParseReportV1, ParsedXbrlFactV1
from .contracts import (
    DimensionV1,
    IssueV1,
    Severity,
    SourceRecordV1,
    SourceProvenanceV1,
)
from .facts import CanonicalMappingV1, FactCandidateV1, FactSelection, select_fact
from .snapshots import SnapshotError


def _candidate_id(
    fact: ParsedXbrlFactV1, *, source: SourceRecordV1, normalized_field: str
) -> str:
    payload = "|".join(
        (
            source.content_hash,
            fact.concept,
            fact.context_id,
            fact.value,
            fact.unit or "",
            fact.decimals or "",
            normalized_field,
        )
    ).encode("utf-8")
    return f"sec-fact-{hashlib.sha256(payload).hexdigest()[:24]}"


def _decimal_value(value: str) -> Decimal | None:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def parsed_facts_to_candidates(
    report: ArelleParseReportV1,
    *,
    source: SourceRecordV1,
    issuer_id: str,
    normalized_field: str,
    mapping: CanonicalMappingV1 | None = None,
) -> tuple[FactCandidateV1, ...]:
    """Convert numeric facts in an offline parser report into candidates.

    Facts without a typed period, unit, or finite numeric value are excluded
    instead of being silently normalized. The caller can inspect the parser
    report and source manifest for the exclusion context.
    """
    if not report.offline:
        raise SnapshotError(
            "PARSER_NOT_OFFLINE", "SEC rebuild requires an offline parser report"
        )
    if report.source_content_hash != source.content_hash:
        raise SnapshotError(
            "SOURCE_HASH_MISMATCH", "parser report is not bound to source bytes"
        )
    if (
        report.parser_version != source.parser_version
        and source.parser_version != f"arelle-release=={report.parser_version}"
    ):
        raise SnapshotError(
            "PARSER_VERSION_MISMATCH",
            "parser report is not bound to source parser metadata",
        )
    if report.blocking_finding_codes():
        raise SnapshotError(
            "PARSER_VALIDATION_BLOCKED",
            "parser validation findings block canonical fact rebuild",
        )
    if mapping is not None and mapping.normalized_field != normalized_field:
        raise SnapshotError(
            "MAPPING_FIELD_MISMATCH",
            "canonical mapping does not target the requested normalized field",
        )
    normalized_issuer = issuer_id.lstrip("0") or "0"
    candidates: list[FactCandidateV1] = []
    provenance = SourceProvenanceV1(
        source_url=source.uri,
        content_hash=source.content_hash,
        source_role=source.role,
        captured_at=source.captured_at,
        available_at=source.available_at,
        filed_at=source.filed_at,
        accession_number=source.accession_number,
        parser_version=source.parser_version,
        taxonomy_version=report.taxonomy_version,
        terms_reference=source.terms_reference,
    )
    for fact in report.facts:
        if mapping is not None and fact.concept != mapping.source_concept:
            continue
        if (
            fact.entity_identifier is None
            or (fact.entity_identifier.lstrip("0") or "0") != normalized_issuer
        ):
            raise SnapshotError(
                "ISSUER_MISMATCH",
                "parsed XBRL entity does not match the requested issuer",
            )
        value = _decimal_value(fact.value) if fact.is_numeric else None
        if value is None or not fact.unit:
            continue
        if fact.period_start is not None and fact.period_end is not None:
            period_type = "duration"
            period_start = fact.period_start
            period_end = fact.period_end
            instant = None
            as_of = datetime.combine(
                period_end, datetime.min.time(), tzinfo=timezone.utc
            )
        elif fact.instant is not None:
            period_type = "instant"
            period_start = None
            period_end = None
            instant = fact.instant
            as_of = datetime.combine(instant, datetime.min.time(), tzinfo=timezone.utc)
        else:
            continue
        currency = (
            fact.unit.rsplit(":", 1)[-1] if fact.unit.startswith("iso4217:") else None
        )
        dimensions = tuple(
            DimensionV1(name=name, member=member) for name, member in fact.dimensions
        )
        candidates.append(
            FactCandidateV1(
                candidate_id=_candidate_id(
                    fact, source=source, normalized_field=normalized_field
                ),
                issuer_id=issuer_id,
                concept=fact.concept,
                normalized_field=normalized_field,
                value=value,
                unit=fact.unit,
                scale=fact.scale,
                currency=currency,
                period_type=period_type,
                period_start=period_start,
                period_end=period_end,
                instant=instant,
                dimensions=dimensions,
                entity_scope=fact.entity_identifier or issuer_id,
                consolidation_scope=fact.consolidation_scope,
                security_scope=fact.security_scope,
                as_of=as_of,
                available_at=source.available_at,
                filed_at=source.filed_at,
                captured_at=source.captured_at,
                accession_number=source.accession_number,
                filing_version=source.filing_version
                or source.accession_number
                or "unknown",
                is_amendment=source.is_amendment,
                amends_accession=source.amends_accession,
                amendment_scope=source.amendment_scope,
                decimals=(
                    int(fact.decimals)
                    if fact.decimals and fact.decimals.lstrip("-").isdigit()
                    else None
                ),
                context_id=fact.context_id,
                unit_qname=fact.unit,
                measure=fact.unit,
                source=provenance,
                taxonomy_version=report.taxonomy_version,
                mapping=mapping,
            )
        )
    return tuple(candidates)


def select_canonical_fact(
    candidates: tuple[FactCandidateV1, ...], valuation_timestamp: datetime
) -> FactSelection:
    """Select the consolidated issuer fact while retaining segment evidence."""
    consolidated = tuple(
        candidate
        for candidate in candidates
        if not candidate.dimensions and candidate.consolidation_scope == "consolidated"
    )
    if not consolidated:
        return FactSelection(
            None,
            tuple(candidate.candidate_id for candidate in candidates),
            (
                IssueV1(
                    code="FACT_CONSOLIDATED_MISSING",
                    severity=Severity.ERROR,
                    message="no consolidated candidate is available for canonical selection",
                    field=candidates[0].normalized_field if candidates else None,
                ),
            ),
        )
    available = tuple(
        candidate
        for candidate in consolidated
        if candidate.available_at <= valuation_timestamp
    )
    latest_period = max((candidate.as_of for candidate in available), default=None)
    period_candidates = (
        tuple(candidate for candidate in available if candidate.as_of == latest_period)
        if latest_period is not None
        else consolidated
    )
    selection = select_fact(
        period_candidates,
        valuation_timestamp,
    )
    if selection.fact is not None:
        selection = FactSelection(
            selection.fact.model_copy(
                update={"rejected_candidates": selection.rejected_candidate_ids}
            ),
            tuple(
                dict.fromkeys(
                    selection.rejected_candidate_ids
                    + tuple(
                        candidate.candidate_id
                        for candidate in candidates
                        if candidate not in consolidated
                    )
                )
            ),
            selection.issues,
        )
    return selection
