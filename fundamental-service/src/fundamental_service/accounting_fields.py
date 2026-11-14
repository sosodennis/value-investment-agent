"""Source-bound field observations for review; no selection or release authority."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .automatic_mapping import (
    AUTOMATIC_MAPPING_POLICY,
    automatic_mapping_policy_digest,
    automatic_mapping_proposals,
)
from .contracts import StrictModel
from .facts import CanonicalMappingV1, FactCandidateV1
from .original_issuer import OriginalIssuerEvidenceV1, OriginalOperatingSourceV1
from .sec_rebuild import parsed_facts_to_candidates
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

FIELD_EXTRACTION_POLICY: Literal["source-bound-field-observations-v1"] = (
    "source-bound-field-observations-v1"
)
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FieldName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class AccountingFieldRequestV1(StrictModel):
    original: OriginalIssuerEvidenceV1
    normalized_fields: tuple[FieldName, ...] = Field(min_length=1, max_length=128)
    mapping_version: str = Field(min_length=1)
    mappings: tuple[CanonicalMappingV1, ...] | None = None

    @field_validator("normalized_fields")
    @classmethod
    def ordered_fields(cls, fields: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(fields)) != len(fields):
            raise ValueError("requested accounting fields must be unique")
        return tuple(sorted(fields))

    @field_validator("mappings")
    @classmethod
    def ordered_mappings(
        cls, mappings: tuple[CanonicalMappingV1, ...] | None
    ) -> tuple[CanonicalMappingV1, ...] | None:
        if mappings is None:
            return None
        if len({m.decision_id for m in mappings}) != len(mappings):
            raise ValueError("supplied mapping identities must be unique")
        return tuple(sorted(mappings, key=lambda m: m.decision_id))

    @model_validator(mode="after")
    def mapping_scope(self) -> AccountingFieldRequestV1:
        if self.mappings is not None and any(
            m.normalized_field not in self.normalized_fields
            or m.mapping_version != self.mapping_version
            for m in self.mappings
        ):
            raise ValueError(
                "supplied mappings must match requested fields and version"
            )
        return self


class FieldCandidateFailureV1(StrictModel):
    mapping_decision_id: str
    reason_code: str


class FieldValueConflictV1(StrictModel):
    """Different values at the same reported scope, across all proposed concepts."""

    scope_digest: Digest
    candidate_ids: tuple[str, ...] = Field(min_length=2)


class AccountingFieldObservationsV1(StrictModel):
    field: FieldName
    proposals: tuple[CanonicalMappingV1, ...]
    candidates: tuple[FactCandidateV1, ...]
    candidate_count: int = Field(ge=0)
    conflicts: tuple[FieldValueConflictV1, ...]
    extraction_failures: tuple[FieldCandidateFailureV1, ...]
    issue_codes: tuple[str, ...]
    status: Literal["requires_semantic_review", "unresolved"]

    @model_validator(mode="after")
    def observations_are_coherent(self) -> AccountingFieldObservationsV1:
        ids = tuple(c.candidate_id for c in self.candidates)
        if (
            ids != tuple(sorted(set(ids)))
            or self.candidate_count != len(ids)
            or self.status != ("requires_semantic_review" if ids else "unresolved")
            or self.issue_codes != tuple(sorted(set(self.issue_codes)))
            or any(c.normalized_field != self.field for c in self.candidates)
            or any(m.normalized_field != self.field for m in self.proposals)
            or self.conflicts != _value_conflicts(self.candidates)
        ):
            raise ValueError("field observations differ from their candidates")
        return self


class AccountingFieldExtractionV1(StrictModel):
    contract_version: Literal["fundamental.accounting-field-extraction.v1"] = (
        "fundamental.accounting-field-extraction.v1"
    )
    policy_version: Literal["source-bound-field-observations-v1"] = (
        FIELD_EXTRACTION_POLICY
    )
    policy_digest: Digest
    mapping_policy_version: str
    mapping_policy_digest: Digest
    mapping_version: str
    mapping_basis: Literal["registered_proposals", "supplied_mappings"]
    source: OriginalOperatingSourceV1
    decision_at: datetime
    original_evidence_digest: Digest
    parser_replay_digest: Digest
    parser_blocking_codes: tuple[str, ...]
    original_issue_codes: tuple[str, ...]
    fields: tuple[AccountingFieldObservationsV1, ...]
    authority: Literal[
        "provisional_candidates_not_approved_mapping_or_model_inputs"
    ] = "provisional_candidates_not_approved_mapping_or_model_inputs"
    input_digest: Digest
    output_digest: Digest

    @model_validator(mode="after")
    def output_is_canonical(self) -> AccountingFieldExtractionV1:
        names = tuple(row.field for row in self.fields)
        if names != tuple(sorted(set(names))) or self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("field extraction order or output digest differs")
        return self


def field_extraction_policy_digest() -> str:
    """Pin this observation policy and the owning mapper's executable rules."""
    return sha256_digest(
        {
            "version": FIELD_EXTRACTION_POLICY,
            "source_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "mapping_policy_digest": automatic_mapping_policy_digest(),
        }
    )


def _value_conflicts(
    candidates: tuple[FactCandidateV1, ...],
) -> tuple[FieldValueConflictV1, ...]:
    groups: dict[str, list[FactCandidateV1]] = defaultdict(list)
    for candidate in candidates:
        scope = candidate.model_dump(
            include={
                "issuer_id",
                "security_id",
                "normalized_field",
                "unit",
                "scale",
                "currency",
                "period_type",
                "period_start",
                "period_end",
                "instant",
                "entity_scope",
                "consolidation_scope",
                "security_scope",
            }
        )
        scope["dimensions"] = sorted((d.name, d.member) for d in candidate.dimensions)
        groups[sha256_digest(scope)].append(candidate)
    return tuple(
        FieldValueConflictV1(
            scope_digest=scope,
            candidate_ids=tuple(sorted(c.candidate_id for c in observations)),
        )
        for scope, observations in sorted(groups.items())
        if any(c.value != observations[0].value for c in observations[1:])
    )


def extract_accounting_fields(
    request: AccountingFieldRequestV1,
) -> AccountingFieldExtractionV1:
    """Reuse formal proposal/conversion rules without selecting financial inputs.

    Every alternative, dimension and conflict is retained. Missing observations
    remain unresolved. Supplied scoped/computed mappings are replayed verbatim;
    their approval and release are separate operations. The original digest
    retains raw observations that the existing converter cannot represent.
    """
    request = AccountingFieldRequestV1.model_validate_json(canonical_bytes(request))
    original = request.original
    rows = []
    for name in request.normalized_fields:
        proposals = (
            automatic_mapping_proposals(
                name, mapping_version=request.mapping_version, original=original
            )
            if request.mappings is None
            else tuple(m for m in request.mappings if m.normalized_field == name)
        )
        candidates: dict[str, FactCandidateV1] = {}
        failures = []
        codes = set(original.issue_codes)
        if original.status != "matched":
            codes.add("ORIGINAL_ISSUER_REFUSED")
        elif original.report.blocking_finding_codes():
            codes.add("PARSER_VALIDATION_BLOCKED")
        else:
            for proposal in proposals:
                try:
                    observations = parsed_facts_to_candidates(
                        original.report,
                        source=original.source,
                        issuer_id=original.source.cik,
                        normalized_field=name,
                        mapping=proposal,
                    )
                except SnapshotError as error:
                    codes.add(error.code)
                    failures.append(
                        FieldCandidateFailureV1(
                            mapping_decision_id=proposal.decision_id,
                            reason_code=error.code,
                        )
                    )
                    continue
                for candidate in observations:
                    candidates[candidate.candidate_id] = candidate
        if not proposals:
            codes.add("NO_EXECUTABLE_MAPPING_PROPOSAL")
        if not candidates:
            codes.add("NO_SOURCE_BOUND_CANDIDATE_IN_SUPPLIED_REPORT")
        ordered = tuple(candidates[key] for key in sorted(candidates))
        conflicts = _value_conflicts(ordered)
        if conflicts:
            codes.add("FIELD_VALUE_CONFLICT_REQUIRES_REVIEW")
        rows.append(
            AccountingFieldObservationsV1(
                field=name,
                proposals=tuple(sorted(proposals, key=lambda p: p.decision_id)),
                candidates=ordered,
                candidate_count=len(ordered),
                conflicts=conflicts,
                extraction_failures=tuple(
                    sorted(failures, key=lambda f: f.mapping_decision_id)
                ),
                issue_codes=tuple(sorted(codes)),
                status="requires_semantic_review" if candidates else "unresolved",
            )
        )
    mapping_digest = automatic_mapping_policy_digest()
    policy_digest = field_extraction_policy_digest()
    payload = {
        "policy_digest": policy_digest,
        "mapping_policy_version": AUTOMATIC_MAPPING_POLICY,
        "mapping_policy_digest": mapping_digest,
        "mapping_version": request.mapping_version,
        "mapping_basis": "registered_proposals"
        if request.mappings is None
        else "supplied_mappings",
        "source": original.source,
        "decision_at": original.decision_at,
        "original_evidence_digest": sha256_digest(original),
        "parser_replay_digest": original.report.replay_digest(),
        "parser_blocking_codes": original.report.blocking_finding_codes(),
        "original_issue_codes": original.issue_codes,
        "fields": tuple(rows),
        "input_digest": sha256_digest(
            {"request": request, "policy_digest": policy_digest}
        ),
    }
    # Include schema defaults in the content digest.
    payload.update(
        {
            "contract_version": "fundamental.accounting-field-extraction.v1",
            "policy_version": FIELD_EXTRACTION_POLICY,
            "authority": "provisional_candidates_not_approved_mapping_or_model_inputs",
        }
    )
    return AccountingFieldExtractionV1.model_validate(
        {
            **payload,
            "output_digest": sha256_digest(payload),
        }
    )
