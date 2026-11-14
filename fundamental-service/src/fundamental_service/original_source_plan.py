"""Compile saved original identity evidence into the existing source plan."""

from __future__ import annotations

import hashlib
from string import Formatter
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, TypeAdapter, model_validator

from .automatic_mapping import automatic_mapping_policy_digest
from .automatic_source_mapping import AutomaticSecIngestionRequestV1
from .classification_crosswalk import ClassificationCrosswalkPolicyV1
from .command_artifacts import EvidenceArtifactStore
from .contracts import (
    FiscalPeriodSelectorV1,
    InitialModelId,
    SecFilingSelectorV1,
    StrictModel,
)
from .data_releases import ArtifactRefV1
from .issuer_country_crosswalk import CountryCrosswalkPolicyV1
from .issuer_classification import IssuerClassificationRequestV1
from .issuer_market_policy_plan import IssuerMarketReferencePlanPolicyV1
from .issuer_market_preparation import IssuerMarketPreparationRequestV1
from .automatic_market_policy import AutomaticMarketPolicyPolicyV1
from .market_source_selection import DailyMarketRatePolicyV1
from .public_acquisition import PublicSourceAcquisitionRequestV1
from .public_admission import PublicSourceAdmissionRequestV1
from .original_preparation import OriginalPreparation
from .policies import initial_model_specs
from .preparation_runner import AutomaticSourcePreparationPlanV1
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .valuation_requirements import (
    composite_working_capital_requirements_profile,
    source_preparation_requirements_profile,
)
from .working_capital import (
    WORKING_CAPITAL_REQUIRED_EXCLUSIONS,
    InclusionScenariosV1,
    working_capital_exclusion_coverage,
)
from .working_capital_preparation import (
    ValuationWorkingCapitalRecipeV1,
    WorkingCapitalExclusionRecipeV1,
    WorkingCapitalPeriodRecipeV1,
)
from .terminal_growth import TerminalGrowthPlanV1


class AutomaticWorkingCapitalRecipeTemplateV1(StrictModel):
    """Deployment-owned recipe policy expanded over retained annual originals."""

    exclusions: tuple[WorkingCapitalExclusionRecipeV1, ...]
    asset_residual: InclusionScenariosV1
    liability_residual: InclusionScenariosV1
    perimeter_rationale: str = Field(min_length=16)

    @model_validator(mode="after")
    def explicit_perimeter(self) -> AutomaticWorkingCapitalRecipeTemplateV1:
        keys = tuple(item.account_class for item in self.exclusions)
        classes = [
            name
            for item in self.exclusions
            for name in working_capital_exclusion_coverage(item.mapped_fact_role)[1]
        ]
        if (
            keys != tuple(sorted(set(keys)))
            or len(classes) != len(set(classes))
            or set(classes) != set(WORKING_CAPITAL_REQUIRED_EXCLUSIONS)
        ):
            raise ValueError("recipe template must cover each exclusion class once")
        if all(
            item.low == item.high
            for item in (self.asset_residual, self.liability_residual)
        ):
            raise ValueError("recipe template residuals require explicit sensitivity")
        return self


class AutomaticPublicSourceRequestTemplateV1(StrictModel):
    """Deployment-owned public source URI template, without source values."""

    source_id: str = Field(min_length=1)
    uri_template: str = Field(min_length=1)
    source_profile: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def safe_uri_template(self) -> AutomaticPublicSourceRequestTemplateV1:
        try:
            fields = tuple(Formatter().parse(self.uri_template))
        except ValueError as error:
            raise ValueError("public source URI template is malformed") from error
        if any(
            field not in {"valuation_year", "valuation_date"}
            or format_spec
            or conversion
            for _, field, format_spec, conversion in fields
            if field is not None
        ):
            raise ValueError("public source URI template has an unsupported field")
        example = self.uri_template.format(
            valuation_year="2000", valuation_date="2000-01-02"
        )
        parsed = urlsplit(example)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("public source URI template must resolve to HTTPS")
        return self

    def render(self, valuation_at: datetime) -> PublicSourceAcquisitionRequestV1:
        if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
            raise ValueError("market source template requires a zoned valuation time")
        valuation_at = valuation_at.astimezone(UTC)
        valuation_date = valuation_at.date()
        uri = self.uri_template.format(
            valuation_year=f"{valuation_date.year:04d}",
            valuation_date=valuation_date.isoformat(),
        )
        return PublicSourceAcquisitionRequestV1(
            source_id=self.source_id,
            uri=uri,
            source_profile=self.source_profile,
            terms_reference=self.terms_reference,
            valuation_timestamp=valuation_at,
        )


class AutomaticMarketSourceTemplateV1(StrictModel):
    """Provider-neutral capture and admission inputs for one market metric."""

    kind: Literal["macro", "reference"]
    provider_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    sources: tuple[AutomaticPublicSourceRequestTemplateV1, ...] = Field(
        min_length=1, max_length=8
    )
    terms: tuple[AutomaticPublicSourceRequestTemplateV1, ...] = Field(
        default=(), max_length=8
    )

    @model_validator(mode="after")
    def unique_requests(self) -> AutomaticMarketSourceTemplateV1:
        if len({item.uri_template for item in self.sources}) != len(self.sources):
            raise ValueError("market source template repeats a source URI")
        if len({item.uri_template for item in self.terms}) != len(self.terms):
            raise ValueError("market source template repeats a terms URI")
        if self.kind == "reference":
            from .market_reference import ReferenceMetric

            TypeAdapter(ReferenceMetric).validate_python(self.metric_id)
        return self


class AutomaticMarketSourcesTemplateV1(StrictModel):
    """One pinned source-use policy and its configured provider requests."""

    source_use_policy_version: str = Field(min_length=1)
    source_use_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_sources: tuple[AutomaticMarketSourceTemplateV1, ...] = Field(
        min_length=1, max_length=16
    )

    @model_validator(mode="after")
    def canonical_sources(self) -> AutomaticMarketSourcesTemplateV1:
        keys = tuple(
            (item.kind, item.provider_id, item.metric_id)
            for item in self.market_sources
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("issuer market source templates must be canonical")
        return self


class AutomaticIssuerMarketPolicyTemplateV1(StrictModel):
    """Deployment-owned provider and policy pins for issuer/date market planning."""

    classification_provider_id: str = Field(min_length=1)
    country_policy: CountryCrosswalkPolicyV1
    industry_policy: ClassificationCrosswalkPolicyV1
    reference_policy: IssuerMarketReferencePlanPolicyV1
    market_policy_version: str = Field(min_length=1)
    risk_free_policy: DailyMarketRatePolicyV1
    terminal_growth_policy_id: str = Field(min_length=1)
    gdp_horizon_years: int = Field(ge=1, le=100)
    maximum_gdp_period_age_days: int = Field(ge=0)
    source_plan_template: AutomaticMarketSourcesTemplateV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def supported_terminal_rate(self) -> AutomaticIssuerMarketPolicyTemplateV1:
        if (
            self.risk_free_policy.currency != "USD"
            or self.risk_free_policy.series_id != "us.treasury_par_yield_10y"
        ):
            raise ValueError(
                "issuer market template requires the configured USD long-term rate"
            )
        return self


def _market_source_requests(
    template: AutomaticMarketSourcesTemplateV1 | None,
    *,
    valuation_at: datetime,
) -> tuple[
    tuple[PublicSourceAcquisitionRequestV1, ...],
    tuple[PublicSourceAdmissionRequestV1, ...],
]:
    if template is None:
        return (), ()
    captures: dict[tuple[str, str], PublicSourceAcquisitionRequestV1] = {}
    admissions = []
    for market_source in template.market_sources:
        sources = tuple(item.render(valuation_at) for item in market_source.sources)
        terms = tuple(item.render(valuation_at) for item in market_source.terms)
        for request in (*sources, *terms):
            previous = captures.setdefault((request.source_id, request.uri), request)
            if previous != request:
                raise ValueError("market source URI has conflicting profile or terms")
        admissions.append(
            PublicSourceAdmissionRequestV1(
                kind=market_source.kind,
                provider_id=market_source.provider_id,
                metric_id=market_source.metric_id,
                valuation_at=valuation_at,
                policy_version=template.source_use_policy_version,
                policy_digest=template.source_use_policy_digest,
                source_request_digests=tuple(sorted(item.digest for item in sources)),
                terms_request_digests=tuple(sorted(item.digest for item in terms)),
            )
        )
    return (
        tuple(sorted(captures.values(), key=lambda item: item.digest)),
        tuple(sorted(admissions, key=lambda item: item.digest)),
    )


class AutomaticSourcePlanConfigurationV1(StrictModel):
    """Deployment choices, without caller-supplied issuer or filing identity."""

    protocol: Literal["automatic-source-plan-configuration-v1"] = (
        "automatic-source-plan-configuration-v1"
    )
    model_id: InitialModelId
    release_profile_id: str = Field(min_length=1, max_length=128)
    coverage_profile: str = Field(min_length=1, max_length=128)
    evaluator_id: str = Field(min_length=1, max_length=128)
    mapping_version: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    working_capital_recipe_template: AutomaticWorkingCapitalRecipeTemplateV1 | None = (
        Field(default=None, exclude_if=lambda value: value is None)
    )
    issuer_market_policy_template: AutomaticIssuerMarketPolicyTemplateV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def supported_model(self) -> AutomaticSourcePlanConfigurationV1:
        source_preparation_requirements_profile(self.model_id)
        if self.working_capital_recipe_template is not None:
            composite_working_capital_requirements_profile(
                self.model_id, operating_only=False
            )
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class OriginalSourcePlanRequestV1(StrictModel):
    protocol: Literal["original-source-plan-request-v1"] = (
        "original-source-plan-request-v1"
    )
    original_preparation: ArtifactRefV1
    configuration: AutomaticSourcePlanConfigurationV1
    runtime_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def original_reference(self) -> OriginalSourcePlanRequestV1:
        if (
            self.original_preparation.role != "sec-original-preparation-v1"
            or self.original_preparation.media_type != "application/json"
        ):
            raise ValueError("source compilation requires original preparation")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class OriginalSourcePlanEvidenceV1(StrictModel):
    protocol: Literal["original-source-plan-v1"] = "original-source-plan-v1"
    request: OriginalSourcePlanRequestV1
    plan: AutomaticSourcePreparationPlanV1 | None
    issue_codes: tuple[str, ...]
    retryable: bool

    @model_validator(mode="after")
    def plan_or_refusal(self) -> OriginalSourcePlanEvidenceV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("source compilation issues must be canonical")
        if (self.plan is None) != bool(self.issue_codes) or (
            self.plan is not None and self.retryable
        ):
            raise ValueError("source compilation needs a plan or retained refusal")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        if self.retryable:
            return f"original-source-plan-attempt:{self.digest}"
        return f"original-source-plan:{self.request.digest}"

    @property
    def plan_ref(self) -> ArtifactRefV1 | None:
        if self.plan is None:
            return None
        return ArtifactRefV1(
            artifact_id=f"source-preparation-plan:{self.plan.digest}",
            content_hash=self.plan.digest,
            media_type="application/json",
            role=self.plan.protocol,
        )

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.request.digest,
                    self.request.configuration.digest,
                    self.request.original_preparation.content_hash,
                    *((self.plan.digest,) if self.plan is not None else ()),
                }
            )
        )


class OriginalSourcePlan:
    def __init__(
        self,
        *,
        originals: OriginalPreparation,
        artifacts: EvidenceArtifactStore,
        compilation_lock: Callable[[str], AbstractContextManager[None]],
    ) -> None:
        self._originals = originals
        self._artifacts = artifacts
        self._lock = compilation_lock

    def _compile(
        self, request: OriginalSourcePlanRequestV1
    ) -> OriginalSourcePlanEvidenceV1:
        reference = request.original_preparation
        if (
            self._originals.reference(reference.artifact_id, reference.role)
            != reference
        ):
            raise SnapshotError("ORIGINAL_SOURCE_PLAN_INVALID", "original differs")
        prepared = self._originals.read(reference.artifact_id)
        codes = set(prepared.issue_codes)
        if not prepared.filings:
            codes.add("ORIGINAL_SOURCE_PLAN_FILINGS_MISSING")
        identities = {
            sha256_digest(item.identity)
            for item in prepared.filings
            if item.identity is not None
        }
        if len(identities) > 1:
            codes.add("ORIGINAL_HISTORY_IDENTITY_CONFLICT")
        if prepared.retryable and not codes:
            codes.add("ORIGINAL_SOURCE_PLAN_RETRYABLE")
        for item in prepared.filings:
            codes.update(item.issue_codes)
            if item.identity is None:
                codes.add("ORIGINAL_SOURCE_PLAN_IDENTITY_MISSING")
        plan = None
        if not codes:
            configuration = request.configuration
            recipe_template = configuration.working_capital_recipe_template
            profile = source_preparation_requirements_profile(
                configuration.model_id,
                composite_inputs=recipe_template is not None,
            )
            model = next(
                model
                for model in initial_model_specs()
                if model.model_id == configuration.model_id
            )
            runtime = prepared.request.runtime
            ingestions = []
            recipe_filings: list[tuple[str, date]] = []
            market_context = None
            market_original: tuple[str, date] | None = None
            for item in prepared.filings:
                validated = self._originals.read_validation(item.validation.artifact_id)
                original = validated.request
                identity = item.identity
                if identity is None:
                    raise SnapshotError(
                        "ORIGINAL_SOURCE_PLAN_INVALID", "original identity is missing"
                    )
                ingestions.append(
                    AutomaticSecIngestionRequestV1(
                        contract_version="fundamental.v1",
                        identity=identity,
                        cik=original.cik,
                        ticker=identity.security_id,
                        identity_basis="original-filing-dei-v1",
                        valuation_timestamp=original.valuation_timestamp,
                        fiscal_period_selector=FiscalPeriodSelectorV1(
                            mode="latest_complete", count=profile.history_window_years
                        ),
                        required_fields=profile.required_fact_fields,
                        source_selection_policy=original.source_selection_policy,
                        supplemental_filing_policy="sec-equity-award-proxy.v2",
                        coverage_profile=configuration.coverage_profile,
                        legal_use_profile="sec-public-us-v1",
                        filing=SecFilingSelectorV1(
                            accession_number=original.filing.accession_number,
                            forms=("10-K",),
                        ),
                        parser_version=runtime.arelle_version,
                        validation_profile_id=runtime.validation_profile_id,
                        taxonomy_manifest_id=runtime.taxonomy_manifest_id,
                        taxonomy_version=runtime.taxonomy_version,
                        policy_version=configuration.policy_version,
                        source_revision=request.runtime_source_revision,
                        evaluator_id=configuration.evaluator_id,
                        mapping_policy_digest=automatic_mapping_policy_digest(),
                        mapping_version=configuration.mapping_version,
                        model_id=configuration.model_id,
                        model_version=model.model_version,
                        requirements_digest=profile.digest,
                    )
                )
                market_template = configuration.issuer_market_policy_template
                if market_template is not None:
                    if identity.currency != "USD":
                        codes.add("ISSUER_MARKET_POLICY_CURRENCY_UNSUPPORTED")
                    if market_context is not None and market_context != (
                        identity.issuer_id,
                        original.valuation_timestamp,
                    ):
                        codes.add("ORIGINAL_HISTORY_MARKET_CONTEXT_CONFLICT")
                    market_context = (
                        identity.issuer_id,
                        original.valuation_timestamp,
                    )
                    original_identity = (
                        original.filing.accession_number,
                        original.filing.report_period_end,
                    )
                    if (
                        market_original is None
                        or original_identity[1] > market_original[1]
                    ):
                        market_original = original_identity
                if recipe_template is not None:
                    recipe_filings.append(
                        (
                            original.filing.accession_number,
                            original.filing.report_period_end,
                        )
                    )
            recipe = None
            if recipe_template is not None:
                if any(
                    period > ingestions[0].valuation_timestamp.date()
                    for _, period in recipe_filings
                ):
                    codes.add("ORIGINAL_HISTORY_PERIOD_NOT_AVAILABLE")
                if len({period for _, period in recipe_filings}) != len(recipe_filings):
                    codes.add("ORIGINAL_HISTORY_PERIOD_CONFLICT")
                if not codes:
                    periods = tuple(
                        WorkingCapitalPeriodRecipeV1(
                            accession_number=accession,
                            period_end=period,
                            exclusions=recipe_template.exclusions,
                            asset_residual=recipe_template.asset_residual,
                            liability_residual=recipe_template.liability_residual,
                            perimeter_rationale=recipe_template.perimeter_rationale,
                        )
                        for accession, period in sorted(
                            recipe_filings, key=lambda item: item[1]
                        )
                    )
                    recipe = ValuationWorkingCapitalRecipeV1(
                        model_id=configuration.model_id,
                        model_version=model.model_version,
                        requirements_profile_digest=composite_working_capital_requirements_profile(
                            configuration.model_id, operating_only=False
                        ).digest,
                        mapping_version=configuration.mapping_version,
                        periods=periods,
                    )
            if codes:
                plan = None
            else:
                market_policy_request = None
                market_template = configuration.issuer_market_policy_template
                if market_template is not None:
                    assert market_context is not None
                    assert market_original is not None
                    issuer_id, valuation_at = market_context
                    accession, period_end = market_original
                    terminal_plan = TerminalGrowthPlanV1(
                        issuer_id=issuer_id,
                        policy_id=market_template.terminal_growth_policy_id,
                        valuation_at=valuation_at,
                        currency="USD",
                        gdp_horizon_years=market_template.gdp_horizon_years,
                        maximum_gdp_period_age_days=(
                            market_template.maximum_gdp_period_age_days
                        ),
                        risk_free_policy=market_template.risk_free_policy,
                    )
                    classification_request = IssuerClassificationRequestV1(
                        issuer_id=issuer_id,
                        accession_number=accession,
                        report_period_end=period_end,
                        valuation_at=valuation_at,
                    )
                    market_policy = AutomaticMarketPolicyPolicyV1(
                        policy_version=market_template.market_policy_version,
                        currency="USD",
                        risk_free_policy=market_template.risk_free_policy,
                        terminal_growth_plan=terminal_plan,
                    )
                    market_policy_request = IssuerMarketPreparationRequestV1(
                        source_revision=request.runtime_source_revision,
                        classification_provider_id=(
                            market_template.classification_provider_id
                        ),
                        classification_request=classification_request,
                        country_policy=market_template.country_policy,
                        industry_policy=market_template.industry_policy,
                        reference_policy=market_template.reference_policy,
                        market_policy=market_policy,
                    )
                    public_sources, source_admissions = _market_source_requests(
                        market_template.source_plan_template, valuation_at=valuation_at
                    )
                else:
                    public_sources, source_admissions = (), ()
                if not codes:
                    plan = AutomaticSourcePreparationPlanV1(
                        source_revision=request.runtime_source_revision,
                        release_profile_id=configuration.release_profile_id,
                        model_id=configuration.model_id,
                        ingestions=tuple(
                            sorted(
                                ingestions,
                                key=lambda item: item.filing.accession_number or "",
                            )
                        ),
                        public_sources=public_sources,
                        source_admissions=source_admissions,
                        valuation_working_capital_recipe=recipe,
                        issuer_market_policy=market_policy_request,
                    )
        return OriginalSourcePlanEvidenceV1(
            request=request,
            plan=plan,
            issue_codes=tuple(sorted(codes)),
            retryable=prepared.retryable,
        )

    def _check_artifact(
        self,
        artifact_id: str,
        value: object,
        dependencies: tuple[str, ...] = (),
    ) -> None:
        record = self._artifacts.get(artifact_id)
        payload = self._artifacts.read(artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or record.dependency_hashes != dependencies
            or record.content_hash != hashlib.sha256(payload).hexdigest()
            or payload != canonical_bytes(value)
        ):
            raise SnapshotError(
                "ORIGINAL_SOURCE_PLAN_INVALID", "retained source plan differs"
            )

    def read(self, artifact_id: str) -> OriginalSourcePlanEvidenceV1:
        try:
            evidence = OriginalSourcePlanEvidenceV1.model_validate_json(
                self._artifacts.read(artifact_id)
            )
        except ValueError as error:
            raise SnapshotError(
                "ORIGINAL_SOURCE_PLAN_INVALID", "invalid retained source plan"
            ) from error
        self._check_artifact(artifact_id, evidence, evidence.dependencies)
        if artifact_id != evidence.artifact_id:
            raise SnapshotError("ORIGINAL_SOURCE_PLAN_INVALID", "plan identity differs")
        request = evidence.request
        self._check_artifact(f"original-source-plan-request:{request.digest}", request)
        self._check_artifact(
            f"source-plan-configuration:{request.configuration.digest}",
            request.configuration,
        )
        if evidence.plan_ref is not None:
            self._check_artifact(evidence.plan_ref.artifact_id, evidence.plan)
        if evidence != self._compile(request):
            raise SnapshotError(
                "ORIGINAL_SOURCE_PLAN_INVALID", "source compilation does not reproduce"
            )
        return evidence

    def execute(
        self, request: OriginalSourcePlanRequestV1
    ) -> tuple[OriginalSourcePlanEvidenceV1, ArtifactPublicationV1]:
        request = OriginalSourcePlanRequestV1.model_validate_json(
            canonical_bytes(request)
        )
        with self._lock(sha256_digest(("original-source-plan", request.digest))):
            artifact_id = f"original-source-plan:{request.digest}"
            try:
                self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                evidence = self.read(artifact_id)
                if evidence.request != request:
                    raise SnapshotError(
                        "ORIGINAL_SOURCE_PLAN_INVALID", "source plan request differs"
                    )
                return evidence, ArtifactPublicationV1(
                    artifact=self._artifacts.get(artifact_id), wrote=False
                )
            evidence = self._compile(request)
            self._artifacts.put_with_receipt(
                f"original-source-plan-request:{request.digest}", request
            )
            configuration = request.configuration
            self._artifacts.put_with_receipt(
                f"source-plan-configuration:{configuration.digest}", configuration
            )
            if evidence.plan_ref is not None:
                self._artifacts.put_with_receipt(
                    evidence.plan_ref.artifact_id, evidence.plan
                )
            publication = self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            self.read(evidence.artifact_id)
            return evidence, publication
