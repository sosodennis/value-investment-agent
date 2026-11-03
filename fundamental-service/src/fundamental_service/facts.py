"""Point-in-time XBRL facts, taxonomy manifests, mappings, and quality gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    CanonicalFactV1,
    DimensionV1,
    IssueV1,
    MissingValueV1,
    PeriodType,
    QualityStatus,
    Severity,
    SourceProvenanceV1,
    XbrlContextV1,
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
        )


@dataclass(frozen=True)
class FactSelection:
    fact: CanonicalFactV1 | None
    rejected_candidate_ids: tuple[str, ...]
    issues: tuple[IssueV1, ...]


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
    eligible = tuple(
        item for item in candidates if item.available_at <= valuation_timestamp
    )
    rejected = [
        item.candidate_id
        for item in candidates
        if item.available_at > valuation_timestamp
    ]
    if not eligible:
        return FactSelection(
            None,
            tuple(rejected),
            (
                IssueV1(
                    code="FACT_NOT_AVAILABLE",
                    severity=Severity.ERROR,
                    message="no fact was available at valuation time",
                ),
            ),
        )
    latest_available = max(item.available_at for item in eligible)
    latest = tuple(item for item in eligible if item.available_at == latest_available)
    precision = max(_precision(item) for item in latest)
    precise = tuple(item for item in latest if _precision(item) == precision)
    values = {repr(item.value) for item in precise}
    if len(values) > 1:
        return FactSelection(
            None,
            tuple(rejected + [item.candidate_id for item in precise]),
            (
                IssueV1(
                    code="FACT_CONFLICT",
                    severity=Severity.FATAL,
                    message="equally precise eligible facts disagree",
                    field=precise[0].normalized_field,
                ),
            ),
        )
    selected = sorted(precise, key=lambda item: item.candidate_id)[0]
    quality = QualityStatus.VERIFIED
    issues: list[IssueV1] = []
    if selected.mapping is not None and selected.mapping.status != "approved":
        quality = QualityStatus.PROVISIONAL
        issues.append(
            IssueV1(
                code="MAPPING_UNRESOLVED",
                severity=Severity.ERROR,
                message="canonical mapping is not approved",
                field=selected.normalized_field,
            )
        )
    return FactSelection(
        selected.canonical_fact(
            quality=quality, issue_codes=tuple(issue.code for issue in issues)
        ),
        tuple(
            rejected
            + [
                item.candidate_id
                for item in latest
                if item.candidate_id != selected.candidate_id
            ]
        ),
        tuple(issues),
    )


def select_fact_groups(
    candidates: Iterable[FactCandidateV1], valuation_timestamp: datetime
) -> tuple[FactSelection, ...]:
    grouped: dict[tuple[object, ...], list[FactCandidateV1]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.fact_key(), []).append(candidate)
    return tuple(select_fact(items, valuation_timestamp) for items in grouped.values())


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
