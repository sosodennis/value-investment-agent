"""Complete mapping coverage of the service-owned model requirements."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .automatic_mapping import AutomaticMappingSourceV1
from .data_releases import ArtifactRefV1, ReleaseModel
from .policies import initial_model_specs
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
            for model in initial_model_specs()
        ):
            raise ValueError("batch requires the exact service model and requirements")
        return self


class AutomaticMappingRoleDecisionV1(ReleaseModel):
    normalized_field: str = Field(min_length=1)
    status: Literal["approved", "abstain"]
    reason_codes: tuple[str, ...]
    decision: ArtifactRefV1 | None
    approval: ArtifactRefV1 | None

    @model_validator(mode="after")
    def approval_requires_a_decision(self) -> AutomaticMappingRoleDecisionV1:
        if self.status == "approved":
            if self.reason_codes or self.decision is None or self.approval is None:
                raise ValueError("approved roles require a decision and certificate")
        elif not self.reason_codes or self.approval is not None:
            raise ValueError("abstained roles require reasons without a certificate")
        return self


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
