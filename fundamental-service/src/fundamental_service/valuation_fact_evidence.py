"""Explain mapped fact availability without granting model or release readiness."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .contracts import CanonicalFactV1, SourceRole, SourceSnapshotV1, StrictModel
from .data_releases import ArtifactRefV1
from .facts import canonical_fact_digest
from .serialization import sha256_digest
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    select_released_facts,
)


class FactEvidenceReferenceV1(StrictModel):
    fact_id: str = Field(min_length=1)
    fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class MappedFactObservationV1(FactEvidenceReferenceV1):
    state: Literal["observed", "derived", "confirmed_absent"]
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_decision_id: str | None
    period_start: date | None
    period_end: date
    instant: date | None
    unit: str


class SourceMappingRefusalV1(StrictModel):
    normalized_field: str = Field(min_length=1)
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_ref: ArtifactRefV1
    proposal_index: int = Field(ge=0)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def refusal_identifies_retained_mapping(self) -> "SourceMappingRefusalV1":
        if (
            self.batch_ref.role != "automatic-mapping-batch-decision-v1"
            or self.batch_ref.media_type != "application/json"
        ):
            raise ValueError("mapping refusals require their retained batch reference")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))) or any(
            not code for code in self.reason_codes
        ):
            raise ValueError("mapping refusal reasons must be nonempty and canonical")
        return self


class FactRoleEvidenceV1(StrictModel):
    normalized_field: str
    required: bool
    state: Literal["observations_available", "unknown"]
    observations: tuple[MappedFactObservationV1, ...]
    rejected_candidates: tuple[FactEvidenceReferenceV1, ...]
    mapping_refusals: tuple[SourceMappingRefusalV1, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def state_matches_observations(self) -> "FactRoleEvidenceV1":
        if (self.state == "unknown") != (not self.observations):
            raise ValueError("unknown fact roles cannot contain accepted observations")
        if {item.fact_digest for item in self.observations} & {
            item.fact_digest for item in self.rejected_candidates
        }:
            raise ValueError("a fact cannot be both accepted and rejected")
        if any(
            item.normalized_field != self.normalized_field
            for item in self.mapping_refusals
        ):
            raise ValueError("mapping refusal must belong to its fact role")
        keys = tuple(sha256_digest(item) for item in self.mapping_refusals)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("mapping refusals must be distinct and ordered")
        return self


class SourceFactEvidenceInventoryV1(StrictModel):
    protocol: Literal["source-fact-evidence-inventory-v1"] = (
        "source-fact-evidence-inventory-v1"
    )
    scope: Literal["mapped_observations_not_completeness_or_model_readiness"] = (
        "mapped_observations_not_completeness_or_model_readiness"
    )
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fact_digests: tuple[str, ...]
    roles: tuple[FactRoleEvidenceV1, ...]

    @model_validator(mode="after")
    def canonical_inventory(self) -> "SourceFactEvidenceInventoryV1":
        names = tuple(row.normalized_field for row in self.roles)
        if names != tuple(sorted(set(names))):
            raise ValueError("fact evidence roles must be distinct and ordered")
        if self.input_fact_digests != tuple(sorted(set(self.input_fact_digests))):
            raise ValueError("fact evidence inputs must be distinct and ordered")
        for row in self.roles:
            for references in (row.observations, row.rejected_candidates):
                digests = tuple(item.fact_digest for item in references)
                if digests != tuple(sorted(set(digests))) or not set(digests) <= set(
                    self.input_fact_digests
                ):
                    raise ValueError("fact evidence must reference canonical inputs")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def build_source_fact_inventory(
    facts: tuple[CanonicalFactV1, ...],
    *,
    snapshot: SourceSnapshotV1,
    profile: ValuationRequirementsProfileV1,
    mapping_refusals: tuple[SourceMappingRefusalV1, ...] = (),
) -> SourceFactEvidenceInventoryV1:
    """Retain every eligible observation, including unresolved duplicate groups.

    Presence is not proof of annual coverage, component completeness or agreement.
    Selection of accounting representations and model admission remain with owners.
    """
    required = set(profile.required_fact_fields)
    roles = sorted(required | set(profile.supporting_fact_fields))
    sources = {
        (record.accession_number, record.content_hash)
        for record in snapshot.source_records
        if record.role is SourceRole.FILING
        and record.available_at <= snapshot.valuation_timestamp
    }
    refusals = {sha256_digest(item): item for item in mapping_refusals}
    if any(
        item.normalized_field not in roles
        or (item.accession_number, item.source_content_hash) not in sources
        for item in refusals.values()
    ):
        raise ValueError(
            "mapping refusals must bind available snapshot sources and roles"
        )
    inputs = {canonical_fact_digest(fact): fact for fact in facts}
    relevant = tuple(inputs[key] for key in sorted(inputs))
    selection = select_released_facts(
        relevant,
        profile=profile,
        snapshot=snapshot,
        valuation_timestamp=snapshot.valuation_timestamp,
    )
    accepted = {canonical_fact_digest(fact) for fact in selection.facts}
    rows = []
    for role in roles:
        observations = []
        rejected = []
        for digest, fact in sorted(inputs.items()):
            if fact.normalized_field != role:
                continue
            reference = {"fact_id": fact.fact_id, "fact_digest": digest}
            if digest not in accepted:
                rejected.append(FactEvidenceReferenceV1(**reference))
                continue
            disposition = (
                fact.accounting_evidence.period_rule.disposition
                if fact.accounting_evidence is not None
                else None
            )
            state: Literal["observed", "derived", "confirmed_absent"] = "observed"
            if disposition in {"derived", "confirmed_absent"}:
                state = "derived" if disposition == "derived" else "confirmed_absent"
            observations.append(
                MappedFactObservationV1(
                    **reference,
                    state=state,
                    source_content_hash=fact.source.content_hash,
                    mapping_decision_id=fact.mapping_decision_id,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    instant=fact.instant,
                    unit=fact.unit,
                )
            )
        rows.append(
            FactRoleEvidenceV1(
                normalized_field=role,
                required=role in required,
                state="observations_available" if observations else "unknown",
                observations=tuple(observations),
                rejected_candidates=tuple(rejected),
                mapping_refusals=tuple(
                    item
                    for _, item in sorted(refusals.items())
                    if item.normalized_field == role
                ),
            )
        )
    return SourceFactEvidenceInventoryV1(
        snapshot_manifest_digest=snapshot.manifest_digest,
        requirements_digest=profile.digest,
        input_fact_digests=tuple(sorted(inputs)),
        roles=tuple(rows),
    )
