"""Point-in-time XBRL facts, taxonomy manifests, mappings, and quality gates."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    CandidateRejectionV1,
    CanonicalFactV1,
    DimensionV1,
    IssueV1,
    MissingValueV1,
    PeriodType,
    QualityStatus,
    Severity,
    SourceProvenanceV1,
    SourceSnapshotV1,
    XbrlContextV1,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


CANONICAL_FACT_DERIVED_DEFAULTS = {
    "rejected_candidates": (),
    "rejected_candidate_reasons": (),
    "point_in_time_policy": None,
    "selection_reason": None,
}


def canonical_fact_digest(fact: CanonicalFactV1) -> str:
    """Digest the immutable fact payload without PIT selection annotations.

    Selection annotations are a derived view added by point-in-time resolution.
    Normalize them to the schema defaults while retaining the existing payload
    shape so manifests created before this helper remain valid.
    """

    payload = fact.model_dump(mode="json")
    payload.update(CANONICAL_FACT_DERIVED_DEFAULTS)
    return sha256_digest(payload)


class CanonicalFactRepository(Protocol):
    """Small immutable fact store used by the public snapshot resolver."""

    def publish(self, fact: CanonicalFactV1) -> None: ...

    def get(self, fact_id: str) -> CanonicalFactV1: ...

    def resolve(
        self,
        *,
        snapshot: "SourceSnapshotV1",
        valuation_timestamp: datetime,
        required_fields: tuple[str, ...],
    ) -> tuple[CanonicalFactV1, ...]: ...


class FilesystemCanonicalFactRepository:
    """Append-only JSON facts addressed by their canonical fact ID."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, fact_id: str) -> Path:
        if not fact_id or fact_id in {".", ".."} or any(c in fact_id for c in "/\\"):
            raise ValueError("fact identifier contains an unsafe path")
        path = (self.root / f"{fact_id}.json").resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("fact path escapes repository root")
        return path

    def publish(self, fact: CanonicalFactV1) -> None:
        path = self._path(fact.fact_id)
        payload = canonical_bytes(fact)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("canonical fact is immutable")
            return
        fd, temporary = tempfile.mkstemp(prefix="fact-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, fact_id: str) -> CanonicalFactV1:
        try:
            return CanonicalFactV1.model_validate_json(self._path(fact_id).read_bytes())
        except (FileNotFoundError, ValueError) as exc:
            raise SnapshotError(
                "FACT_NOT_FOUND", f"fact {fact_id} is unavailable"
            ) from exc

    def resolve(
        self,
        *,
        snapshot: "SourceSnapshotV1",
        valuation_timestamp: datetime,
        required_fields: tuple[str, ...],
    ) -> tuple[CanonicalFactV1, ...]:
        candidates: list[CanonicalFactV1] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                fact = CanonicalFactV1.model_validate_json(path.read_bytes())
            except (OSError, ValueError):
                continue
            candidates.append(fact)
        return resolve_canonical_facts(
            candidates,
            snapshot=snapshot,
            valuation_timestamp=valuation_timestamp,
            required_fields=required_fields,
        )


class PinnedValidationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: Literal["sec-efm-us-gaap-v1"] = "sec-efm-us-gaap-v1"
    arelle_version: Literal["2.47.4"] = "2.47.4"
    dqc_version: Literal["v31.0.3"] = "v31.0.3"
    xule_version: Literal["30055"] = "30055"
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaxonomyPackageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    package_id: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    effective_from: date
    effective_to: date | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entrypoints: tuple[str, ...] = ()
    validation_profile: PinnedValidationProfile


class TaxonomyManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    manifest_id: str = Field(min_length=1)
    packages: tuple[TaxonomyPackageV1, ...] = Field(min_length=1)
    dts_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1)


class ValidationFindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    severity: Literal["info", "warning", "error", "fatal"]
    field: str | None = None
    message: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    blocks_verified: bool


class CanonicalMappingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    decision_id: str = Field(min_length=1)
    source_concept: str = Field(min_length=1)
    normalized_field: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    anchor_concept: str | None = None
    confidence: Literal["high", "medium", "low", "unresolved"]
    evidence_refs: tuple[str, ...] = ()
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["approved", "provisional", "ambiguous", "rejected"]

    @model_validator(mode="after")
    def extension_review(self) -> "CanonicalMappingV1":
        is_extension = (
            ":" in self.source_concept
            and not self.source_concept.startswith("us-gaap:")
        )
        if (
            is_extension
            and self.status == "approved"
            and (not self.anchor_concept or not self.reviewer or not self.evidence_refs)
        ):
            raise ValueError(
                "approved extension mappings require an anchor, reviewer, and evidence"
            )
        if self.confidence == "unresolved" and self.status == "approved":
            raise ValueError("unresolved mappings cannot be approved")
        return self


class FactCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    security_id: str | None = None
    concept: str = Field(min_length=1)
    normalized_field: str = Field(min_length=1)
    value: Decimal | str | bool | MissingValueV1
    unit: str = Field(min_length=1)
    scale: int
    currency: str | None = None
    period_type: PeriodType
    period_start: date | None = None
    period_end: date | None = None
    instant: date | None = None
    dimensions: tuple[DimensionV1, ...] = ()
    entity_scope: str = Field(min_length=1)
    consolidation_scope: str = Field(min_length=1)
    security_scope: str = Field(min_length=1)
    as_of: datetime
    available_at: datetime
    filed_at: datetime | None = None
    captured_at: datetime
    accession_number: str | None = None
    filing_version: str = Field(min_length=1)
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None
    decimals: int | None = None
    context_id: str = Field(min_length=1)
    unit_qname: str = Field(min_length=1)
    measure: str = Field(min_length=1)
    source: SourceProvenanceV1
    taxonomy_version: str = Field(min_length=1)
    mapping: CanonicalMappingV1 | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "FactCandidateV1":
        if self.period_type is PeriodType.INSTANT and self.instant is None:
            raise ValueError("instant candidate requires instant")
        if self.period_type is PeriodType.DURATION and (
            self.period_start is None or self.period_end is None
        ):
            raise ValueError("duration candidate requires period_start and period_end")
        return self

    def fact_key(self) -> tuple[object, ...]:
        dimensions = tuple(sorted((item.name, item.member) for item in self.dimensions))
        return (
            self.issuer_id,
            self.security_id,
            self.concept,
            self.period_type,
            self.period_start,
            self.period_end,
            self.instant,
            self.unit,
            self.currency,
            dimensions,
            self.entity_scope,
            self.consolidation_scope,
            self.security_scope,
        )

    def canonical_fact(
        self, *, quality: QualityStatus, issue_codes: tuple[str, ...] = ()
    ) -> CanonicalFactV1:
        context = XbrlContextV1(
            concept_qname=self.concept,
            period_type=self.period_type,
            start_date=self.period_start,
            end_date=self.period_end,
            instant=self.instant,
            unit_qname=self.unit_qname,
            measure=self.measure,
            dimensions=self.dimensions,
            entity_scope=self.entity_scope,
            consolidation_scope=self.consolidation_scope,
            context_id=self.context_id,
        )
        return CanonicalFactV1(
            contract_version="fundamental.v1",
            fact_id=self.candidate_id,
            issuer_id=self.issuer_id,
            security_id=self.security_id,
            concept=self.concept,
            normalized_field=self.normalized_field,
            value=self.value,
            unit=self.unit,
            scale=self.scale,
            currency=self.currency,
            period_start=self.period_start,
            period_end=self.period_end or self.instant,
            instant=self.instant,
            context=context,
            as_of=self.as_of,
            available_at=self.available_at,
            filed_at=self.filed_at,
            captured_at=self.captured_at,
            accession_number=self.accession_number,
            taxonomy_version=self.taxonomy_version,
            source=self.source,
            quality=quality,
            issue_codes=issue_codes,
            mapping_decision_id=self.mapping.decision_id if self.mapping else None,
            mapping_confidence=self.mapping.confidence if self.mapping else None,
            security_scope=self.security_scope,
            filing_version=self.filing_version,
            is_amendment=self.is_amendment,
            amends_accession=self.amends_accession,
            supersedes_accession=self.supersedes_accession,
            amendment_scope=self.amendment_scope,
            decimals=self.decimals,
        )


@dataclass(frozen=True)
class FactSelection:
    fact: CanonicalFactV1 | None
    rejected_candidate_ids: tuple[str, ...]
    issues: tuple[IssueV1, ...]
    rejected_candidate_reasons: tuple[CandidateRejectionV1, ...] = ()


def _precision(candidate: FactCandidateV1) -> int:
    """XBRL decimals: larger values are more precise; None is least precise."""
    return candidate.decimals if candidate.decimals is not None else -(10**9)


def select_fact(
    candidates: Iterable[FactCandidateV1], valuation_timestamp: datetime
) -> FactSelection:
    candidates = tuple(candidates)
    if not candidates:
        return FactSelection(
            None,
            (),
            (
                IssueV1(
                    code="FACT_MISSING",
                    severity=Severity.ERROR,
                    message="no candidates",
                ),
            ),
        )
    unknown_amendments = tuple(
        item
        for item in candidates
        if item.is_amendment
        and item.available_at <= valuation_timestamp
        and item.amendment_scope in {None, "unknown"}
    )
    if unknown_amendments:
        return FactSelection(
            None,
            tuple(sorted(item.candidate_id for item in candidates)),
            (
                IssueV1(
                    code="FACT_AMENDMENT_SCOPE_UNKNOWN",
                    severity=Severity.FATAL,
                    message="eligible amendment facts lack a reviewed amendment scope",
                    field=unknown_amendments[0].normalized_field,
                ),
            ),
            tuple(
                CandidateRejectionV1(
                    candidate_id=item.candidate_id,
                    reason="eligible_amendment_scope_unknown",
                )
                for item in sorted(
                    candidates, key=lambda candidate: candidate.candidate_id
                )
            ),
        )
    eligible = tuple(
        item
        for item in candidates
        if item.available_at <= valuation_timestamp
        and not (item.is_amendment and item.amendment_scope == "unrelated")
    )
    rejected_reasons = {
        item.candidate_id: "not_available_at_valuation_time"
        for item in candidates
        if item.available_at > valuation_timestamp
    }
    rejected_reasons.update(
        {
            item.candidate_id: "unrelated_amendment_cannot_supersede_fact"
            for item in candidates
            if item.is_amendment and item.amendment_scope == "unrelated"
        }
    )
    if not eligible:
        return FactSelection(
            None,
            tuple(sorted(rejected_reasons)),
            (
                IssueV1(
                    code="FACT_NOT_AVAILABLE",
                    severity=Severity.ERROR,
                    message="no fact was available at valuation time",
                ),
            ),
            tuple(
                CandidateRejectionV1(candidate_id=key, reason=value)
                for key, value in sorted(rejected_reasons.items())
            ),
        )
    by_filing: dict[tuple[str | None, str, str], list[FactCandidateV1]] = {}
    for item in eligible:
        filing_key = (
            item.accession_number,
            item.filing_version,
            item.source.content_hash,
        )
        by_filing.setdefault(filing_key, []).append(item)
    filing_selections: list[FactCandidateV1] = []
    for filing_candidates in by_filing.values():
        available_in_filing = tuple(
            item
            for item in filing_candidates
            if item.available_at
            == max(candidate.available_at for candidate in filing_candidates)
        )
        precision = max(_precision(item) for item in available_in_filing)
        precise_in_filing = tuple(
            item for item in available_in_filing if _precision(item) == precision
        )
        if len({repr(item.value) for item in precise_in_filing}) > 1:
            return FactSelection(
                None,
                tuple(
                    sorted(
                        set(rejected_reasons)
                        | {item.candidate_id for item in precise_in_filing}
                    )
                ),
                (
                    IssueV1(
                        code="FACT_CONFLICT",
                        severity=Severity.FATAL,
                        message="equally precise facts in one filing disagree",
                        field=precise_in_filing[0].normalized_field,
                    ),
                ),
                tuple(
                    CandidateRejectionV1(candidate_id=key, reason=value)
                    for key, value in sorted(
                        {
                            **rejected_reasons,
                            **{
                                item.candidate_id: "equal_precision_conflict_in_filing"
                                for item in precise_in_filing
                            },
                        }.items()
                    )
                ),
            )
        selected_in_filing = min(precise_in_filing, key=lambda item: item.candidate_id)
        filing_selections.append(selected_in_filing)
        rejected_reasons.update(
            {
                item.candidate_id: "lower_precision_within_filing"
                for item in filing_candidates
                if item not in precise_in_filing
                and item.available_at
                == max(candidate.available_at for candidate in filing_candidates)
            }
        )
        rejected_reasons.update(
            {
                item.candidate_id: "superseded_by_later_available_candidate_in_filing"
                for item in filing_candidates
                if item not in available_in_filing
            }
        )
        rejected_reasons.update(
            {
                item.candidate_id: "equivalent_fact_candidate_in_filing"
                for item in precise_in_filing
                if item.candidate_id != selected_in_filing.candidate_id
            }
        )

    latest_available = max(item.available_at for item in filing_selections)
    latest = tuple(
        item for item in filing_selections if item.available_at == latest_available
    )
    rejected_reasons.update(
        {
            item.candidate_id: "superseded_by_later_available_filing"
            for item in filing_selections
            if item.available_at < latest_available
        }
    )
    if len({repr(item.value) for item in latest}) > 1:
        return FactSelection(
            None,
            tuple(
                sorted(set(rejected_reasons) | {item.candidate_id for item in latest})
            ),
            (
                IssueV1(
                    code="FACT_CONFLICT",
                    severity=Severity.FATAL,
                    message=(
                        "equally recent filing facts disagree for the same fact key"
                    ),
                    field=latest[0].normalized_field,
                ),
            ),
            tuple(
                CandidateRejectionV1(candidate_id=key, reason=value)
                for key, value in sorted(
                    {
                        **rejected_reasons,
                        **{
                            item.candidate_id: (
                                "equal_availability_conflict_across_filings"
                            )
                            for item in latest
                        },
                    }.items()
                )
            ),
        )
    selected = min(latest, key=lambda item: item.candidate_id)
    rejected_reasons.update(
        {
            item.candidate_id: "equivalent_fact_candidate_across_filings"
            for item in latest
            if item.candidate_id != selected.candidate_id
        }
    )
    quality = QualityStatus.VERIFIED
    issues: list[IssueV1] = []
    if selected.mapping is None or selected.mapping.status != "approved":
        quality = QualityStatus.PROVISIONAL
        issues.append(
            IssueV1(
                code="MAPPING_UNRESOLVED",
                severity=Severity.ERROR,
                message="canonical mapping is missing or not approved",
                field=selected.normalized_field,
            )
        )
    fact = selected.canonical_fact(
        quality=quality, issue_codes=tuple(issue.code for issue in issues)
    ).model_copy(
        update={
            "rejected_candidates": tuple(sorted(rejected_reasons)),
            "rejected_candidate_reasons": tuple(
                CandidateRejectionV1(candidate_id=candidate_id, reason=reason)
                for candidate_id, reason in sorted(rejected_reasons.items())
            ),
            "point_in_time_policy": "pit-v1",
            "selection_reason": "latest_available_then_highest_xbrl_decimals",
        }
    )
    reason_records = tuple(
        CandidateRejectionV1(candidate_id=key, reason=value)
        for key, value in sorted(rejected_reasons.items())
    )
    fact = fact.model_copy(update={"rejected_candidate_reasons": reason_records})
    return FactSelection(
        fact,
        tuple(sorted(rejected_reasons)),
        tuple(issues),
        reason_records,
    )


def select_fact_groups(
    candidates: Iterable[FactCandidateV1], valuation_timestamp: datetime
) -> tuple[FactSelection, ...]:
    grouped: dict[tuple[object, ...], list[FactCandidateV1]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.fact_key(), []).append(candidate)
    return tuple(select_fact(items, valuation_timestamp) for items in grouped.values())


def resolve_canonical_facts(
    candidates: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    valuation_timestamp: datetime,
    required_fields: tuple[str, ...],
) -> tuple[CanonicalFactV1, ...]:
    """Resolve stored facts through one shared, deterministic PIT policy."""

    source_records = {item.content_hash: item for item in snapshot.source_records}
    requested = set(required_fields)
    eligible: list[CanonicalFactV1] = []
    rejected_reasons: dict[str, str] = {}
    for fact in candidates:
        if fact.normalized_field not in requested:
            continue
        source = source_records.get(fact.source.content_hash)
        if fact.issuer_id != snapshot.identity.issuer_id:
            rejected_reasons[fact.fact_id] = "issuer_mismatch"
            continue
        if fact.security_id not in {None, snapshot.identity.security_id}:
            rejected_reasons[fact.fact_id] = "security_mismatch"
            continue
        if fact.quality is not QualityStatus.VERIFIED:
            rejected_reasons[fact.fact_id] = "fact_quality_not_verified"
            continue
        if source is None:
            rejected_reasons[fact.fact_id] = "source_not_in_snapshot"
            continue
        if (
            fact.available_at > valuation_timestamp
            or source.available_at > valuation_timestamp
        ):
            rejected_reasons[fact.fact_id] = "not_available_at_valuation_time"
            continue
        is_amendment = fact.is_amendment or source.is_amendment
        amendment_scope = fact.amendment_scope or source.amendment_scope
        if is_amendment and amendment_scope in {None, "unknown"}:
            raise SnapshotError(
                "FACT_AMENDMENT_SCOPE_UNKNOWN",
                "eligible amendment facts lack a reviewed amendment scope",
            )
        if is_amendment and amendment_scope == "unrelated":
            rejected_reasons[fact.fact_id] = "unrelated_amendment_cannot_supersede_fact"
            continue
        eligible.append(fact)

    fact_groups: dict[tuple[object, ...], list[CanonicalFactV1]] = {}
    for fact in eligible:
        fact_groups.setdefault(_canonical_fact_key(fact, snapshot), []).append(fact)

    selected_by_key: list[CanonicalFactV1] = []
    for group in fact_groups.values():
        chosen, key_rejections = _select_canonical_fact_key(group)
        rejected_reasons.update(key_rejections)
        selected_by_key.append(chosen)

    filing_groups: dict[tuple[str | None, str | None, str], list[CanonicalFactV1]] = {}
    for fact in selected_by_key:
        filing_key = (
            fact.accession_number,
            fact.filing_version,
            fact.source.content_hash,
        )
        filing_groups.setdefault(filing_key, []).append(fact)
    selected_by_filing: list[CanonicalFactV1] = []
    for group in filing_groups.values():
        chosen, key_rejections = _select_latest_period_in_filing(group)
        rejected_reasons.update(key_rejections)
        selected_by_filing.append(chosen)

    resolved: list[CanonicalFactV1] = []
    for field in required_fields:
        field_facts = [
            fact for fact in selected_by_filing if fact.normalized_field == field
        ]
        if not field_facts:
            raise SnapshotError(
                "FACT_NOT_FOUND",
                f"no verified canonical fact is available for {field}",
            )
        latest_available = max(fact.available_at for fact in field_facts)
        latest_period = tuple(
            fact for fact in field_facts if fact.available_at == latest_available
        )
        latest_keys = {_canonical_fact_key(fact, snapshot) for fact in latest_period}
        if len(latest_keys) != 1:
            raise SnapshotError(
                "FACT_CONFLICT",
                f"multiple canonical fact keys are eligible for {field}",
            )
        chosen = min(latest_period, key=lambda fact: fact.fact_id)
        rejected_reasons.update(
            {
                fact.fact_id: "superseded_by_later_available_filing"
                for fact in field_facts
                if fact.available_at < latest_available
            }
        )
        selected_rejections = {
            fact_id: reason
            for fact_id, reason in rejected_reasons.items()
            if fact_id != chosen.fact_id
        }
        resolved.append(
            chosen.model_copy(
                update={
                    "rejected_candidates": tuple(sorted(selected_rejections)),
                    "rejected_candidate_reasons": tuple(
                        CandidateRejectionV1(candidate_id=fact_id, reason=reason)
                        for fact_id, reason in sorted(selected_rejections.items())
                    ),
                    "point_in_time_policy": "pit-v1",
                    "selection_reason": (
                        "latest_available_after_fact_key_point_in_time_selection"
                    ),
                }
            )
        )
    return tuple(resolved)


def _select_latest_period_in_filing(
    candidates: list[CanonicalFactV1],
) -> tuple[CanonicalFactV1, dict[str, str]]:
    latest_end = max(fact.period_end or fact.instant for fact in candidates)
    latest_period = tuple(
        fact for fact in candidates if (fact.period_end or fact.instant) == latest_end
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
        fact for fact in latest_period if durations[fact.fact_id] == longest_duration
    )
    if len(preferred) != 1:
        raise SnapshotError(
            "FACT_CONFLICT",
            "multiple fact keys remain for the selected period",
        )
    chosen = preferred[0]
    return chosen, {
        fact.fact_id: "superseded_by_later_period_within_filing"
        for fact in candidates
        if fact.fact_id != chosen.fact_id
    }


def _canonical_precision(fact: CanonicalFactV1) -> int:
    return fact.decimals if fact.decimals is not None else -(10**9)


def _select_canonical_fact_key(
    candidates: list[CanonicalFactV1],
) -> tuple[CanonicalFactV1, dict[str, str]]:
    rejected: dict[str, str] = {}
    by_filing: dict[tuple[str | None, str | None, str], list[CanonicalFactV1]] = {}
    for fact in candidates:
        filing_key = (
            fact.accession_number,
            fact.filing_version,
            fact.source.content_hash,
        )
        by_filing.setdefault(filing_key, []).append(fact)

    filing_selections: list[CanonicalFactV1] = []
    for filing_candidates in by_filing.values():
        latest_available = max(fact.available_at for fact in filing_candidates)
        latest = tuple(
            fact for fact in filing_candidates if fact.available_at == latest_available
        )
        rejected.update(
            {
                fact.fact_id: "superseded_by_later_available_candidate_in_filing"
                for fact in filing_candidates
                if fact.available_at < latest_available
            }
        )
        precision = max(_canonical_precision(fact) for fact in latest)
        precise = tuple(
            fact for fact in latest if _canonical_precision(fact) == precision
        )
        rejected.update(
            {
                fact.fact_id: "lower_precision_within_filing"
                for fact in latest
                if fact not in precise
            }
        )
        if len({repr(fact.value) for fact in precise}) > 1:
            raise SnapshotError(
                "FACT_CONFLICT",
                "equally precise facts in one filing disagree for the same fact key",
            )
        chosen = min(precise, key=lambda fact: fact.fact_id)
        rejected.update(
            {
                fact.fact_id: "equivalent_fact_candidate_in_filing"
                for fact in precise
                if fact.fact_id != chosen.fact_id
            }
        )
        filing_selections.append(chosen)

    latest_available = max(fact.available_at for fact in filing_selections)
    latest = tuple(
        fact for fact in filing_selections if fact.available_at == latest_available
    )
    rejected.update(
        {
            fact.fact_id: "superseded_by_later_available_filing"
            for fact in filing_selections
            if fact.available_at < latest_available
        }
    )
    if len({repr(fact.value) for fact in latest}) > 1:
        raise SnapshotError(
            "FACT_CONFLICT",
            "equally recent filings disagree for the same fact key",
        )
    chosen = min(latest, key=lambda fact: fact.fact_id)
    rejected.update(
        {
            fact.fact_id: "equivalent_fact_candidate_across_filings"
            for fact in latest
            if fact.fact_id != chosen.fact_id
        }
    )
    return chosen, rejected


def _canonical_fact_key(
    fact: CanonicalFactV1, snapshot: SourceSnapshotV1
) -> tuple[object, ...]:
    dimensions = tuple(
        sorted((item.name, item.member) for item in fact.context.dimensions)
    )
    return (
        fact.issuer_id,
        fact.security_id or snapshot.identity.security_id,
        fact.concept,
        fact.context.period_type,
        fact.period_start,
        fact.period_end,
        fact.instant,
        fact.unit,
        fact.currency,
        dimensions,
        fact.context.entity_scope,
        fact.context.consolidation_scope,
        fact.security_scope or snapshot.identity.share_class,
    )


def quality_gate(
    *,
    findings: Iterable[ValidationFindingV1],
    mappings: Iterable[CanonicalMappingV1],
) -> QualityStatus:
    if any(
        finding.blocks_verified or finding.severity in {"fatal", "error"}
        for finding in findings
    ):
        return QualityStatus.ABSTAIN
    if any(
        mapping.status != "approved" or mapping.confidence in {"low", "unresolved"}
        for mapping in mappings
    ):
        return QualityStatus.PROVISIONAL
    return QualityStatus.VERIFIED
