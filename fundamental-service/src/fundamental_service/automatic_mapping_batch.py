"""Complete mapping coverage of the service-owned model requirements."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .automatic_mapping import AutomaticMappingSourceV1
from .data_releases import ArtifactRefV1, ReleaseModel
from .policies import executable_model_specs
from .statement_contracts import StatementProfileV1
from .statement_profiles import annual_statement_profile, statement_executable_digest
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    automatic_source_requirements_profile,
)


class AutomaticMappingBatchRequestV1(AutomaticMappingSourceV1):
    protocol: Literal["fundamental.automatic-mapping-batch-input.v1"] = (
        "fundamental.automatic-mapping-batch-input.v1"
    )
    mapping_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    requirements: ValuationRequirementsProfileV1

    @model_validator(mode="after")
    def requirements_are_service_owned(self) -> AutomaticMappingBatchRequestV1:
        try:
            profile = automatic_source_requirements_profile(
                self.requirements.model_id, self.requirements.digest
            )
        except ValueError as error:
            raise ValueError(
                "batch requires the exact service model and requirements"
            ) from error
        if self.requirements != profile or not any(
            model.model_id == self.requirements.model_id
            and model.model_version == self.model_version
            for model in executable_model_specs()
        ):
            raise ValueError("batch requires the exact service model and requirements")
        return self

    @property
    def role_fields(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(self.requirements.required_fact_fields)
                | set(self.requirements.supporting_fact_fields)
            )
        )

    @property
    def coverage_digest(self) -> str:
        return self.requirements.digest


class StatementMappingBatchRequestV1(AutomaticMappingSourceV1):
    protocol: Literal["fundamental.statement-mapping-batch-input.v1"] = (
        "fundamental.statement-mapping-batch-input.v1"
    )
    mapping_version: str = Field(min_length=1)
    statement_profile: StatementProfileV1

    @model_validator(mode="after")
    def statement_profile_is_service_owned(self) -> StatementMappingBatchRequestV1:
        if self.statement_profile != annual_statement_profile(
            executable_digest=statement_executable_digest()
        ):
            raise ValueError(
                "statement batch requires the exact installed statement profile"
            )
        return self

    @property
    def role_fields(self) -> tuple[str, ...]:
        return tuple(sorted(row.row_id for row in self.statement_profile.rows))

    @property
    def coverage_digest(self) -> str:
        return self.statement_profile.digest


class AutomaticMappingProposalDecisionV1(ReleaseModel):
    status: Literal["approved", "abstain"]
    reason_codes: tuple[str, ...]
    decision: ArtifactRefV1 | None
    approval: ArtifactRefV1 | None

    @model_validator(mode="after")
    def approval_requires_a_decision(self) -> AutomaticMappingProposalDecisionV1:
        if self.status == "approved":
            if self.reason_codes or self.decision is None or self.approval is None:
                raise ValueError("approved roles require a decision and certificate")
        elif not self.reason_codes or self.approval is not None:
            raise ValueError("abstained roles require reasons without a certificate")
        return self


class AutomaticMappingRoleDecisionV1(AutomaticMappingProposalDecisionV1):
    normalized_field: str = Field(min_length=1)
    additional_decisions: tuple[AutomaticMappingProposalDecisionV1, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )

    def proposal_decisions(self) -> tuple[AutomaticMappingProposalDecisionV1, ...]:
        return (self, *self.additional_decisions)


class AutomaticMappingBatchDecisionV1(ReleaseModel):
    protocol: Literal["fundamental.automatic-mapping-batch-decision.v1"] = (
        "fundamental.automatic-mapping-batch-decision.v1"
    )
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_version: str
    requirements: ValuationRequirementsProfileV1
    roles: tuple[AutomaticMappingRoleDecisionV1, ...]

    @model_validator(mode="after")
    def every_required_role_is_retained(self) -> AutomaticMappingBatchDecisionV1:
        expected = tuple(
            sorted(
                set(self.requirements.required_fact_fields)
                | set(self.requirements.supporting_fact_fields)
            )
        )
        if tuple(role.normalized_field for role in self.roles) != expected:
            raise ValueError("batch decisions must retain every role once in order")
        return self


class StatementMappingBatchDecisionV1(ReleaseModel):
    protocol: Literal["fundamental.statement-mapping-batch-decision.v1"] = (
        "fundamental.statement-mapping-batch-decision.v1"
    )
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    statement_profile: StatementProfileV1
    roles: tuple[AutomaticMappingRoleDecisionV1, ...]

    @model_validator(mode="after")
    def every_statement_role_is_retained(self) -> StatementMappingBatchDecisionV1:
        if tuple(role.normalized_field for role in self.roles) != tuple(
            sorted(row.row_id for row in self.statement_profile.rows)
        ):
            raise ValueError("statement batch decisions must retain every declared row")
        return self
