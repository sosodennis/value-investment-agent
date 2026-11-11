"""Offline rebuild from captured SEC/XBRL bytes to canonical facts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .arelle_parser import ArelleParseReportV1, ParsedXbrlFactV1, fact_semantic_digest
from .accounting_roles import (
    AccountingRoleError,
    AccountingRoleEvidenceV1,
    evaluate_period_rule,
)
from .serialization import sha256_digest
from .contracts import (
    CandidateRejectionV1,
    DimensionV1,
    IssueV1,
    PeriodType,
    Severity,
    SourceProvenanceV1,
    SourceRecordV1,
)
from .facts import (
    CanonicalMappingV1,
    FactCandidateV1,
    FactSelection,
    select_fact_groups,
)
from .snapshots import SnapshotError


def _candidate_id(
    fact: ParsedXbrlFactV1,
    *,
    source: SourceRecordV1,
    normalized_field: str,
    security_id: str | None,
    mapping: CanonicalMappingV1 | None,
) -> str:
    payload = "|".join(
        (
            source.content_hash,
            source.captured_at.isoformat(),
            security_id or "",
            fact.concept,
            fact.context_id,
            fact.value,
            fact.unit or "",
            fact.decimals or "",
            normalized_field,
            mapping.decision_id if mapping else "",
            mapping.mapping_version if mapping else "",
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
    security_id: str | None = None,
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
    expected_parser_hash = source.parser_input_hash or source.content_hash
    if report.source_content_hash != expected_parser_hash:
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
    if mapping is not None and mapping.accounting_rules is not None:
        return _accounting_candidates(
            report,
            source=source,
            provenance=provenance,
            mapping=mapping,
            issuer_id=issuer_id,
            security_id=security_id,
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
            period_type = PeriodType.DURATION
            period_start = fact.period_start
            period_end = fact.period_end
            instant = None
            as_of = datetime.combine(
                period_end, datetime.min.time(), tzinfo=timezone.utc
            )
        elif fact.instant is not None:
            period_type = PeriodType.INSTANT
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
                    fact,
                    source=source,
                    normalized_field=normalized_field,
                    security_id=security_id,
                    mapping=mapping,
                ),
                issuer_id=issuer_id,
                security_id=security_id,
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
                supersedes_accession=source.supersedes_accession,
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


def _accounting_candidates(
    report: ArelleParseReportV1,
    *,
    source: SourceRecordV1,
    provenance: SourceProvenanceV1,
    mapping: CanonicalMappingV1,
    issuer_id: str,
    security_id: str | None,
) -> tuple[FactCandidateV1, ...]:
    rules = mapping.accounting_rules
    assert rules is not None
    if (
        rules.issuer_id != issuer_id
        or rules.security_id != security_id
        or rules.accession_number != source.accession_number
        or rules.raw_content_hash != source.content_hash
        or rules.parser_input_hash != report.source_content_hash
        or rules.parser_fact_digest != fact_semantic_digest(report)
        or source.is_amendment
        or source.form != "10-K"
        or report.validation_profile.validation_mode != "sec-efm-dqc"
        or not {"sec-efm", "dqc-us"}.issubset(report.validation_engines)
    ):
        raise SnapshotError(
            "ACCOUNTING_ROLE_SOURCE_MISMATCH",
            "accounting rules require their exact validated original and issuer",
        )
    by_digest = {sha256_digest(fact): fact for fact in report.facts}
    candidates = []
    for rule in rules.periods:
        if rule.period.period_end > source.available_at.date():
            raise SnapshotError(
                "ACCOUNTING_ROLE_FUTURE_PERIOD",
                "accounting rule cannot assert a future financial period",
            )
        if rule.disposition in {"unknown", "unsupported"}:
            continue
        references = rule.source_references()
        try:
            source_facts = tuple(
                sorted((by_digest[key] for key in set(references)), key=sha256_digest)
            )
        except KeyError as error:
            raise SnapshotError(
                "ACCOUNTING_ROLE_SOURCE_MISMATCH",
                "accounting source observation is unavailable",
            ) from error
        if rule.disposition == "derived":
            for selected in source_facts:
                comparable = tuple(
                    fact
                    for fact in report.facts
                    if fact.concept == selected.concept
                    and fact.entity_identifier == selected.entity_identifier
                    and fact.period_start == selected.period_start
                    and fact.period_end == selected.period_end
                    and fact.instant == selected.instant
                    and fact.unit == selected.unit
                    and fact.dimensions == selected.dimensions
                    and fact.consolidation_scope == selected.consolidation_scope
                )
                if len({_decimal_value(fact.value) for fact in comparable}) != 1:
                    raise SnapshotError(
                        "ACCOUNTING_COMPONENT_CONFLICT",
                        "original contains conflicting accounting observations",
                    )
        try:
            value = evaluate_period_rule(rules, rule, source_facts)
            evidence = AccountingRoleEvidenceV1(
                rule_set=rules, period_rule=rule, source_facts=source_facts, value=value
            )
        except AccountingRoleError as error:
            raise SnapshotError(error.code, str(error)) from error
        assert value is not None
        period = rule.period
        candidates.append(
            FactCandidateV1(
                candidate_id=f"sec-role-{sha256_digest({'mapping': sha256_digest(mapping), 'evidence': evidence})}",
                issuer_id=issuer_id,
                security_id=security_id,
                concept=mapping.source_concept,
                normalized_field=mapping.normalized_field,
                value=value,
                unit=rules.unit,
                scale=0,
                decimals=rule.disclosed_amount.reported_decimals
                if rule.disclosed_amount is not None
                else None,
                currency=rules.currency,
                period_type=PeriodType.INSTANT
                if period.instant
                else PeriodType.DURATION,
                period_start=period.period_start,
                period_end=None if period.instant else period.period_end,
                instant=period.period_end if period.instant else None,
                dimensions=(),
                entity_scope=issuer_id,
                consolidation_scope="consolidated",
                security_scope="security",
                as_of=datetime.combine(
                    period.period_end, datetime.min.time(), tzinfo=timezone.utc
                ),
                available_at=source.available_at,
                filed_at=source.filed_at,
                captured_at=source.captured_at,
                accession_number=source.accession_number,
                filing_version=source.filing_version
                or source.accession_number
                or "unknown",
                context_id=f"computed-{sha256_digest(evidence)}",
                unit_qname=rules.unit,
                measure=rules.unit,
                source=provenance,
                taxonomy_version=report.taxonomy_version,
                mapping=mapping,
                accounting_evidence=evidence,
            )
        )
    return tuple(candidates)


def select_canonical_fact(
    candidates: tuple[FactCandidateV1, ...], valuation_timestamp: datetime
) -> FactSelection:
    """Select one fact-key result and refuse ambiguous normalized-field ties."""
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
                    message=(
                        "no consolidated candidate is available for canonical selection"
                    ),
                    field=candidates[0].normalized_field if candidates else None,
                ),
            ),
        )
    grouped_selections = select_fact_groups(consolidated, valuation_timestamp)
    rejected = tuple(
        sorted(
            {
                candidate_id
                for selection in grouped_selections
                for candidate_id in selection.rejected_candidate_ids
            }
            | {
                candidate.candidate_id
                for candidate in candidates
                if candidate not in consolidated
            }
        )
    )
    rejected_reasons = {
        record.candidate_id: record.reason
        for selection in grouped_selections
        for record in selection.rejected_candidate_reasons
    }
    rejected_reasons.update(
        {
            candidate.candidate_id: "non_consolidated_or_dimensional_candidate"
            for candidate in candidates
            if candidate not in consolidated
        }
    )
    failed_selections = tuple(
        selection for selection in grouped_selections if selection.fact is None
    )
    fatal_issues = tuple(
        issue
        for selection in failed_selections
        for issue in selection.issues
        if issue.severity is Severity.FATAL
    )
    selected = tuple(
        selection.fact for selection in grouped_selections if selection.fact is not None
    )
    if fatal_issues:
        return FactSelection(
            None,
            rejected,
            fatal_issues,
            tuple(
                CandidateRejectionV1(candidate_id=key, reason=value)
                for key, value in sorted(rejected_reasons.items())
            ),
        )
    if not selected:
        return FactSelection(
            None,
            rejected,
            tuple(
                issue for selection in failed_selections for issue in selection.issues
            ),
            tuple(
                CandidateRejectionV1(candidate_id=key, reason=value)
                for key, value in sorted(rejected_reasons.items())
            ),
        )
    filing_groups: dict[tuple[str | None, str | None, str], list] = {}
    for fact in selected:
        filing_key = (
            fact.accession_number,
            fact.filing_version,
            fact.source.content_hash,
        )
        filing_groups.setdefault(filing_key, []).append(fact)
    filing_selections = []
    for filing_candidates in filing_groups.values():
        latest_end = max(fact.period_end or fact.instant for fact in filing_candidates)
        latest_period = tuple(
            fact
            for fact in filing_candidates
            if (fact.period_end or fact.instant) == latest_end
        )
        durations = {
            fact.fact_id: (
                (fact.period_end - fact.period_start).days
                if fact.period_start is not None and fact.period_end is not None
                else 0
            )
            for fact in latest_period
        }
        longest_duration = max(durations.values())
        preferred = tuple(
            fact
            for fact in latest_period
            if durations[fact.fact_id] == longest_duration
        )
        if len(preferred) > 1:
            rejected_reasons.update(
                {
                    fact.fact_id: "ambiguous_period_key_within_filing"
                    for fact in preferred
                }
            )
            return FactSelection(
                None,
                tuple(sorted(set(rejected) | {fact.fact_id for fact in preferred})),
                (
                    IssueV1(
                        code="FACT_CONFLICT",
                        severity=Severity.FATAL,
                        message="multiple fact keys remain for the selected period",
                        field=preferred[0].normalized_field,
                    ),
                ),
                tuple(
                    CandidateRejectionV1(candidate_id=key, reason=value)
                    for key, value in sorted(rejected_reasons.items())
                ),
            )
        chosen = preferred[0]
        rejected_reasons.update(
            {
                fact.fact_id: "superseded_by_later_period_within_filing"
                for fact in filing_candidates
                if fact.fact_id != chosen.fact_id
            }
        )
        filing_selections.append(chosen)
    latest_available = max(fact.available_at for fact in filing_selections)
    latest = tuple(
        fact for fact in filing_selections if fact.available_at == latest_available
    )
    latest_keys = {
        (
            fact.concept,
            fact.context.period_type,
            fact.period_start,
            fact.period_end,
            fact.instant,
            fact.unit,
            fact.currency,
            tuple(sorted((item.name, item.member) for item in fact.context.dimensions)),
            fact.context.entity_scope,
            fact.context.consolidation_scope,
            fact.security_scope,
            fact.security_id,
        )
        for fact in latest
    }
    if len(latest_keys) != 1:
        rejected_reasons.update(
            {fact.fact_id: "ambiguous_latest_fact_key" for fact in latest}
        )
        return FactSelection(
            None,
            tuple(sorted(set(rejected) | {fact.fact_id for fact in latest})),
            (
                IssueV1(
                    code="FACT_CONFLICT",
                    severity=Severity.FATAL,
                    message=(
                        "multiple canonical fact keys map to the latest required field"
                    ),
                    field=latest[0].normalized_field,
                ),
            ),
            tuple(
                CandidateRejectionV1(candidate_id=key, reason=value)
                for key, value in sorted(rejected_reasons.items())
            ),
        )
    fact = min(latest, key=lambda item: item.fact_id)
    selected_issues = next(
        selection.issues
        for selection in grouped_selections
        if selection.fact is not None and selection.fact.fact_id == fact.fact_id
    )
    rejected = tuple(
        sorted(set(rejected) | {item.fact_id for item in selected if item != fact})
    )
    rejected_reasons.update(
        {
            item.fact_id: "superseded_by_later_available_filing"
            for item in selected
            if item.fact_id != fact.fact_id
        }
    )
    reason_records = tuple(
        CandidateRejectionV1(candidate_id=key, reason=value)
        for key, value in sorted(rejected_reasons.items())
    )
    fact = fact.model_copy(
        update={
            "rejected_candidates": rejected,
            "rejected_candidate_reasons": reason_records,
            "point_in_time_policy": "pit-v1",
            "selection_reason": (
                "latest_available_after_fact_key_point_in_time_selection"
            ),
        }
    )
    return FactSelection(fact, rejected, selected_issues, reason_records)
