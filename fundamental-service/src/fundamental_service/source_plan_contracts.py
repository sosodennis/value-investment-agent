"""Versioned source-plan inputs shared by compilation and execution."""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeAlias, TypeVar

from pydantic import Field, TypeAdapter, model_validator

from .automatic_source_mapping import AutomaticSecIngestionRequestV1
from .contracts import (
    InitialModelId,
    SecIngestionRequestV1,
    SecMappingReferenceV1,
    SecSourceRequestV1,
    SnapshotResolutionRequestV1,
    StrictModel,
)
from .data_releases import DataReleaseError
from .issuer_market_preparation import IssuerMarketPreparationRequestV1
from .public_acquisition import PublicSourceAcquisitionRequestV1, PublicSourceCutoffV1
from .public_admission import PublicSourceAdmissionRequestV1
from .serialization import sha256_digest
from .valuation_requirements import (
    ValuationRequirementsProfileV1,
    source_preparation_requirements_profile,
)
from .valuation_release_inputs import valuation_input_requirements
from .working_capital import ValuationWorkingCapitalPolicyV1
from .working_capital_preparation import ValuationWorkingCapitalRecipeV1


SourceRequestT = TypeVar("SourceRequestT", bound=SecSourceRequestV1)


class _SourcePreparationPlan(StrictModel, Generic[SourceRequestT]):
    """Common issuer, chronology and runtime constraints for source plans."""

    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_profile_id: str = Field(min_length=1)
    model_id: InitialModelId
    ingestions: tuple[SourceRequestT, ...] = Field(min_length=1, max_length=6)
    public_sources: tuple[PublicSourceAcquisitionRequestV1, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    source_admissions: tuple[PublicSourceAdmissionRequestV1, ...] = Field(
        default=(), max_length=32, exclude_if=lambda value: not value
    )
    public_source_cutoff: PublicSourceCutoffV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    issuer_market_policy: IssuerMarketPreparationRequestV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    valuation_working_capital_policy: ValuationWorkingCapitalPolicyV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    valuation_working_capital_recipe: ValuationWorkingCapitalRecipeV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @property
    def working_capital_spec(
        self,
    ) -> ValuationWorkingCapitalPolicyV1 | ValuationWorkingCapitalRecipeV1 | None:
        return (
            self.valuation_working_capital_policy
            or self.valuation_working_capital_recipe
        )

    @property
    def requirements_profile(self) -> ValuationRequirementsProfileV1:
        return source_preparation_requirements_profile(
            self.model_id,
            composite_inputs=self.working_capital_spec is not None,
        )

    @model_validator(mode="after")
    def requirements_match(self) -> _SourcePreparationPlan[SourceRequestT]:
        profile = self.requirements_profile
        recipe = self.valuation_working_capital_recipe
        if recipe is not None and (
            self.valuation_working_capital_policy is not None
            or recipe.model_id != self.model_id
            or any(
                item.accession_number
                not in {request.filing.accession_number for request in self.ingestions}
                or item.period_end > self.ingestions[0].valuation_timestamp.date()
                for item in recipe.periods
            )
        ):
            raise ValueError(
                "source recipe must exclusively pin the plan model and filings"
            )
        try:
            valuation_input_requirements(
                self.valuation_working_capital_policy, self.model_id
            )
        except DataReleaseError as error:
            raise ValueError(str(error)) from error
        required = set(profile.required_fact_fields)
        requested = {
            field for request in self.ingestions for field in request.required_fields
        }
        if not required <= requested <= required | set(profile.supporting_fact_fields):
            raise ValueError("source plan must cover the complete model requirements")
        first = self.ingestions[0]
        market = self.issuer_market_policy
        if market is not None and (
            market.source_revision != self.source_revision
            or market.classification_request.issuer_id != first.identity.issuer_id
            or market.classification_request.valuation_at != first.valuation_timestamp
            or market.market_policy.currency != first.identity.currency
            or market.classification_request.accession_number
            not in {item.filing.accession_number for item in self.ingestions}
        ):
            raise ValueError("issuer market request must pin the source plan context")
        cutoff = self.public_source_cutoff
        if cutoff is not None and (
            cutoff.valuation_at != first.valuation_timestamp
            or tuple(item.request for item in cutoff.captures) != self.public_sources
        ):
            raise ValueError(
                "current cutoff must pin the complete plan captures and date"
            )
        if len({request.digest for request in self.public_sources}) != len(
            self.public_sources
        ) or any(
            request.valuation_timestamp
            != (
                cutoff.requested_at if cutoff is not None else first.valuation_timestamp
            )
            for request in self.public_sources
        ):
            raise ValueError(
                "public source requests must be distinct and pin plan date"
            )
        if len({request.digest for request in self.source_admissions}) != len(
            self.source_admissions
        ) or any(
            request.valuation_at != first.valuation_timestamp
            or not set(
                (*request.source_request_digests, *request.terms_request_digests)
            )
            <= {item.digest for item in self.public_sources}
            for request in self.source_admissions
        ):
            raise ValueError(
                "source admissions must be distinct and pin plan captures and date"
            )
        if any(
            request.quote_selection is not None
            and (
                request.quote_selection.issuer_id != first.identity.issuer_id
                or request.quote_selection.security_id != first.identity.security_id
            )
            for request in self.source_admissions
        ):
            raise ValueError("quote selections must pin the source plan identity")
        if self.valuation_working_capital_policy is not None and any(
            item.issuer_id != first.identity.issuer_id
            or item.accession_number
            not in {request.filing.accession_number for request in self.ingestions}
            for item in self.valuation_working_capital_policy.inputs
        ):
            raise ValueError(
                "composite source inputs must pin the plan issuer and filings"
            )
        for request in self.ingestions:
            if any(
                getattr(request, field) != getattr(first, field)
                for field in (
                    "identity",
                    "cik",
                    "ticker",
                    "identity_basis",
                    "valuation_timestamp",
                    "fiscal_period_selector",
                    "coverage_profile",
                    "source_selection_policy",
                    "legal_use_profile",
                    "parser_version",
                    "policy_version",
                    "taxonomy_manifest_id",
                    "taxonomy_version",
                    "validation_profile_id",
                )
            ):
                raise ValueError(
                    "source plan components must share issuer, date and runtime profile"
                )
        if len(self.ingestions) > 1:
            accessions = tuple(
                request.filing.accession_number for request in self.ingestions
            )
            if (
                None in accessions
                or len(set(accessions)) != len(accessions)
                or any(request.filing.forms != ("10-K",) for request in self.ingestions)
            ):
                raise ValueError(
                    "history plan requires distinct pinned original annual filings"
                )
            if accessions != tuple(
                sorted(accession for accession in accessions if accession is not None)
            ):
                raise ValueError("history plan accessions must be sorted")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    def resolution_request(self) -> SnapshotResolutionRequestV1:
        first = self.ingestions[0]
        return SnapshotResolutionRequestV1(
            contract_version="fundamental.v1",
            release_profile_id=self.release_profile_id,
            identity=first.identity,
            valuation_timestamp=first.valuation_timestamp,
            source_selection_policy="pit-v1",
            coverage_profile=first.coverage_profile,
            required_fields=self.requirements_profile.required_fact_fields,
        )


class SourcePreparationPlanV2(_SourcePreparationPlan[SecIngestionRequestV1]):
    """Explicit deployment input with pre-existing mapping decisions."""

    protocol: Literal["source-preparation-v2"] = "source-preparation-v2"

    @model_validator(mode="after")
    def mapping_references_match(self) -> SourcePreparationPlanV2:
        references: dict[str, SecMappingReferenceV1] = {}
        for request in self.ingestions:
            for reference in request.mappings:
                if (
                    self.working_capital_spec is not None
                    and reference.mapping_version
                    != self.working_capital_spec.mapping_version
                ):
                    raise ValueError(
                        "composite source plan must pin one mapping version"
                    )
                previous = references.setdefault(reference.decision_id, reference)
                if previous != reference:
                    raise ValueError("source plan mapping references must be coherent")
        return self


class AutomaticSourcePreparationPlanV1(
    _SourcePreparationPlan[AutomaticSecIngestionRequestV1]
):
    protocol: Literal["automatic-source-preparation-v1"] = (
        "automatic-source-preparation-v1"
    )

    @model_validator(mode="after")
    def automatic_pins_match(self) -> AutomaticSourcePreparationPlanV1:
        first = self.ingestions[0]
        for request in self.ingestions:
            if (
                request.source_revision != self.source_revision
                or request.model_id != self.model_id
                or request.requirements_digest != self.requirements_profile.digest
                or (
                    self.working_capital_spec is not None
                    and request.mapping_version
                    != self.working_capital_spec.mapping_version
                )
                or any(
                    getattr(request, field) != getattr(first, field)
                    for field in (
                        "evaluator_id",
                        "mapping_policy_digest",
                        "mapping_version",
                        "model_version",
                        "requirements_digest",
                    )
                )
            ):
                raise ValueError(
                    "automatic source plan must pin one model, authority and policy"
                )
        return self


SourcePreparationPlan: TypeAlias = Annotated[
    SourcePreparationPlanV2 | AutomaticSourcePreparationPlanV1,
    Field(discriminator="protocol"),
]
SOURCE_PREPARATION_PLAN = TypeAdapter(SourcePreparationPlan)
