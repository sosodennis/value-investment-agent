from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from .fiscal_admission_history import FiscalHistoryHeadV1
from .replay import ArtifactRecordV1

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import QualityStatus, StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_statement_contracts import FiscalObservationV1
from .fiscal_validation_contracts import (
    FiscalValidationPinV1,
    FiscalValidationRuntimeV1,
)
from .history_recovery_contracts import FiscalIssuanceContextV1
from .serialization import canonical_bytes, sha256_digest
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


class FiscalCandidateContentV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-candidate-content.v1"] = (
        "fundamental.fiscal-candidate-content.v1"
    )
    discovery_ref: ArtifactRefV1
    materialization: FiscalValidationPinV1
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

    @model_validator(mode="after")
    def exact_source_set(self) -> FiscalCandidateContentV1:
        scopes = tuple(item.scope for item in self.source_uses)
        if len({item.scope_digest for item in scopes}) != len(scopes):
            raise ValueError("candidate source uses must be unique")
        if any(
            item.issuer_id != self.scope.issuer_id or item.cutoff_at != self.cutoff_at
            for item in scopes
        ):
            raise ValueError("candidate source use differs from issuer or cutoff")
        if (
            len(self.mapping_refs) != 2 * len(scopes)
            or len({ref.artifact_id for ref in self.mapping_refs})
            != len(self.mapping_refs)
            or any(
                ref.role != "fiscal-statement-mapping-v1"
                for ref in self.mapping_refs[::2]
            )
            or any(
                ref.role != "fiscal-mapping-approval" for ref in self.mapping_refs[1::2]
            )
        ):
            raise ValueError(
                "candidate mappings and approvals must cover every source exactly once"
            )
        if self.source_set_digest != sha256_digest(self.source_uses):
            raise ValueError("candidate source-set digest differs")
        return self

    @property
    def content_digest(self) -> str:
        return sha256_digest(self)

    @property
    def dependency_hashes(self) -> tuple[str, ...]:
        hashes = {
            self.discovery_ref.content_hash,
            self.projection_ref.content_hash,
            self.source_set_digest,
            *(ref.content_hash for ref in self.mapping_refs),
        }
        for use in self.source_uses:
            hashes.add(use.scope.source_validation_ref.content_hash)
            hashes.update(ref.content_hash for ref in use.scope.parser_action_refs)
            if isinstance(use, ClassifiedSourceForCandidateV1):
                hashes.update(ref.content_hash for ref in use.classification_refs)
                if use.scope.witness_ref is not None:
                    hashes.add(use.scope.witness_ref.content_hash)
        return tuple(sorted(hashes))


class FiscalPrepareCandidateCommandV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.prepare-fiscal-candidate.v1"] = (
        "fundamental.prepare-fiscal-candidate.v1"
    )
    command_id: str = Field(min_length=1, max_length=256)
    discovery_ref: ArtifactRefV1
    security_id: str | None = Field(default=None, min_length=1, max_length=256)
    classification_bindings: tuple[FiscalCandidateClassificationBindingV1, ...] = ()
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def exact_bindings(self) -> FiscalPrepareCandidateCommandV1:
        if (
            self.discovery_ref.role != "fiscal-discovery"
            or self.discovery_ref.media_type != "application/json"
        ):
            raise ValueError("candidate command requires its exact discovery reference")
        if any(
            len({ref.artifact_id for ref in binding.classification_refs})
            != len(binding.classification_refs)
            for binding in self.classification_bindings
        ):
            raise ValueError("candidate classification references must be unique")
        identities = tuple(
            binding.source_validation_ref.artifact_id
            for binding in self.classification_bindings
        )
        if identities != tuple(sorted(set(identities))):
            raise ValueError("classification bindings must be sorted and unique")
        return self

    @property
    def command_digest(self) -> str:
        return sha256_digest(self)

    @property
    def locator_digest(self) -> str:
        return sha256_digest((self.protocol, self.command_id))

    def artifact_id(self, role: str) -> str:
        return role + ":" + self.locator_digest


class FiscalCandidatePreparationExecutionV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    authority_id: str = Field(min_length=1, max_length=256)
    grant_ref: ArtifactRefV1
    principal_id: str = Field(min_length=1, max_length=256)
    principal_kind: Literal["machine"] = "machine"
    key_id: Digest
    execution_id: str = Field(pattern=r"^candidate-job:[0-9a-f]{32}$")
    issuance: FiscalIssuanceContextV1
    command_digest: Digest
    content_digest: Digest
    preparation_executable_digest: Digest
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_execution(self) -> FiscalCandidatePreparationExecutionV1:
        if self.completed_at < self.started_at:
            raise ValueError("candidate execution clock reversed")
        return self


class FiscalCandidateBodyV2(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-candidate-body.v2"] = (
        "fundamental.fiscal-candidate-body.v2"
    )
    command: FiscalPrepareCandidateCommandV1
    content: FiscalCandidateContentV1
    preparation: FiscalCandidatePreparationExecutionV1
    issuance: FiscalIssuanceContextV1
    signed_at: AwareDatetime

    @model_validator(mode="after")
    def exact_execution(self) -> FiscalCandidateBodyV2:
        if (
            self.command.discovery_ref != self.content.discovery_ref
            or self.command.security_id != self.content.scope.security_id
            or self.preparation.command_digest != self.command.command_digest
            or self.preparation.content_digest != self.content.content_digest
            or self.preparation.issuance != self.issuance
            or not self.preparation.completed_at
            <= self.signed_at
            < self.command.expires_at
        ):
            raise ValueError("candidate body differs from command or execution")
        return self


class FiscalStatementCandidateV2(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-statement-candidate.v2"] = (
        "fundamental.fiscal-statement-candidate.v2"
    )
    body: FiscalCandidateBodyV2
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.body)

    @property
    def candidate_digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return self.body.command.artifact_id("fiscal-statement-candidate-v2")


@dataclass(frozen=True)
class VerifiedFiscalActivity:
    purpose: Literal[
        "source_preparation",
        "focus_validation",
        "source_classification",
        "candidate_preparation",
    ]
    authority_id: str
    principal_id: str
    principal_kind: Literal["machine", "human"] | None
    key_id: str
    grant_ref: ArtifactRefV1 | None
    execution_ids: tuple[str, ...]
    evidence_refs: tuple[ArtifactRefV1, ...]


@dataclass(frozen=True)
class VerifiedRawCandidateSource:
    source_use: VerifiedRawSourceForCandidateV1
    parser_action_refs: tuple[ArtifactRefV1, ...]
    consumed_metadata: tuple[ArtifactRecordV1, ...]


@dataclass(frozen=True)
class VerifiedClassifiedCandidateSource:
    source_use: ClassifiedSourceForCandidateV1
    activities: tuple[VerifiedFiscalActivity, ...]
    consumed_metadata: tuple[ArtifactRecordV1, ...]
    history_heads: tuple[FiscalHistoryHeadV1, ...]
    expires_at: tuple[datetime, ...]


VerifiedFiscalCandidateSource = (
    VerifiedRawCandidateSource | VerifiedClassifiedCandidateSource
)
