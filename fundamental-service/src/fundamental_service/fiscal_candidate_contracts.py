from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import QualityStatus, StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_statement_contracts import FiscalObservationV1
from .fiscal_validation_contracts import FiscalValidationRuntimeV1
from .serialization import sha256_digest
from .statement_contracts import StatementScopeV1

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class FiscalSourceUseScopeV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-source-use-scope.v1"] = (
        "fundamental.fiscal-source-use-scope.v1"
    )
    source_validation_ref: ArtifactRefV1
    validation_kind: Literal["complete_matched", "complete_refused"]
    source_binding_digest: Digest
    issuer_id: str
    accession_number: str
    cutoff_at: AwareDatetime
    runtime: FiscalValidationRuntimeV1
    raw_report_digest: Digest
    parser_action_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    witness_ref: ArtifactRefV1 | None = None
    display_profile_digest: Digest
    mapping_policy_digest: Digest
    permitted_inputs: tuple[FiscalObservationV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_source_inputs(self) -> FiscalSourceUseScopeV1:
        if self.validation_kind == "complete_refused" and self.witness_ref is None:
            raise ValueError("refused candidate source use requires an exact witness")
        if self.validation_kind == "complete_matched" and self.witness_ref is not None:
            raise ValueError("raw-pass source use cannot carry a refusal witness")
        if self.validation_kind == "complete_refused" and any(
            item.quality is not QualityStatus.PROVISIONAL
            for item in self.permitted_inputs
        ):
            raise ValueError(
                "refused source use must preserve provisional observations"
            )
        identities = tuple(item.observation_id for item in self.permitted_inputs)
        if len(set(identities)) != len(identities):
            raise ValueError("source use observation identities must be unique")
        if any(
            item.issuer_id != self.issuer_id
            or item.accession_number != self.accession_number
            or item.source_artifact_id != self.source_validation_ref.artifact_id
            or item.source_binding_digest != self.source_binding_digest
            or item.available_at > self.cutoff_at
            or item.accepted_at > self.cutoff_at
            for item in self.permitted_inputs
        ):
            raise ValueError("source use inputs differ from the exact source scope")
        return self

    @property
    def scope_digest(self) -> str:
        return sha256_digest(self)


class VerifiedRawSourceForCandidateV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["raw_pass"] = "raw_pass"
    scope: FiscalSourceUseScopeV1

    @model_validator(mode="after")
    def requires_raw_pass(self) -> VerifiedRawSourceForCandidateV1:
        if self.scope.validation_kind != "complete_matched":
            raise ValueError("raw-pass candidate input requires matched validation")
        return self


class ClassifiedSourceForCandidateV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["classified_provisional"] = "classified_provisional"
    scope: FiscalSourceUseScopeV1
    classification_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    quality: Literal["provisional"] = "provisional"

    @model_validator(mode="after")
    def preserves_raw_refusal(self) -> ClassifiedSourceForCandidateV1:
        if self.scope.validation_kind != "complete_refused":
            raise ValueError("classified candidate input must retain raw refusal")
        if len({ref.artifact_id for ref in self.classification_refs}) != len(
            self.classification_refs
        ):
            raise ValueError("candidate classification references must be unique")
        return self


FiscalCandidateSourceUseV1 = Annotated[
    VerifiedRawSourceForCandidateV1 | ClassifiedSourceForCandidateV1,
    Field(discriminator="kind"),
]


class FiscalCandidateClassificationBindingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    source_validation_ref: ArtifactRefV1
    witness_ref: ArtifactRefV1
    classification_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)


class FiscalStatementCandidateV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-statement-candidate.v1"] = (
        "fundamental.fiscal-statement-candidate.v1"
    )
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    source_uses: tuple[FiscalCandidateSourceUseV1, ...] = Field(min_length=1)
    mapping_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    projection_ref: ArtifactRefV1
    period_set_digest: Digest
    row_lineage_digest: Digest
    source_set_digest: Digest
    projection_policy_digest: Digest
    executable_digest: Digest
    preparer_execution_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_source_set(self) -> FiscalStatementCandidateV1:
        scopes = tuple(item.scope for item in self.source_uses)
        if len({item.scope_digest for item in scopes}) != len(scopes):
            raise ValueError("candidate source uses must be unique")
        if any(
            item.issuer_id != self.scope.issuer_id or item.cutoff_at != self.cutoff_at
            for item in scopes
        ):
            raise ValueError("candidate source use differs from issuer or cutoff")
        if self.source_set_digest != sha256_digest(self.source_uses):
            raise ValueError("candidate source-set digest differs")
        return self

    @property
    def candidate_digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return f"fiscal-statement-candidate-v1:{self.candidate_digest}"
