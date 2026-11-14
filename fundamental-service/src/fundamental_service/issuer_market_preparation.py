"""Prepare persistent issuer market evidence through existing policy owners."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .automatic_market_policy import AutomaticMarketPolicyPolicyV1
from .automatic_market_policy_evidence import (
    AUTOMATIC_MARKET_POLICY_ROLE,
    AutomaticMarketPolicyEvidenceV1,
    build_automatic_market_policy_evidence,
)
from .classification_crosswalk import (
    ClassificationCrosswalkPolicyV1,
    ClassificationCrosswalkProviderPort,
    IndustryCrosswalkEvidenceV1,
    apply_industry_crosswalk,
)
from .contracts import SourceSnapshotV1, StrictModel
from .data_releases import ArtifactRefV1
from .issuer_classification import (
    IssuerClassificationEvidenceV1,
    IssuerClassificationProviderPort,
    IssuerClassificationRequestV1,
    reproduce_issuer_classification,
)
from .issuer_country_crosswalk import (
    CountryCrosswalkPolicyV1,
    CountryCrosswalkProviderPort,
    IssuerCountryCrosswalkEvidenceV1,
    apply_country_crosswalk,
)
from .issuer_market_policy_plan import (
    IssuerMarketReferencePlanPolicyV1,
    build_issuer_market_reference_plan,
)
from .market_reference_evidence import MARKET_REFERENCE_PLAN_ROLE
from .public_admission import AdmissionArtifactWriter
from .replay import ArtifactPublicationV1
from .serialization import sha256_digest
from .snapshots import SnapshotError
from .source_admission import SourceAdmissionV1
from .source_evidence import RetainedSourceV1
from .terminal_growth_evidence import TERMINAL_GROWTH_PLAN_ROLE


class IssuerMarketPreparationRequestV1(StrictModel):
    protocol: Literal["issuer-market-preparation-request-v1"] = (
        "issuer-market-preparation-request-v1"
    )
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    classification_provider_id: str = Field(min_length=1)
    classification_request: IssuerClassificationRequestV1
    country_policy: CountryCrosswalkPolicyV1
    industry_policy: ClassificationCrosswalkPolicyV1
    reference_policy: IssuerMarketReferencePlanPolicyV1
    market_policy: AutomaticMarketPolicyPolicyV1

    @model_validator(mode="after")
    def same_context(self) -> IssuerMarketPreparationRequestV1:
        terminal = self.market_policy.terminal_growth_plan
        if (
            terminal.issuer_id != self.classification_request.issuer_id
            or terminal.valuation_at != self.classification_request.valuation_at
        ):
            raise ValueError("issuer market preparation must pin one issuer and date")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    def at(self, valuation_at: datetime) -> IssuerMarketPreparationRequestV1:
        """Freeze all dependent decision times together in explicit current mode."""
        payload = self.model_dump()
        payload["classification_request"]["valuation_at"] = valuation_at
        payload["market_policy"]["terminal_growth_plan"]["valuation_at"] = valuation_at
        return IssuerMarketPreparationRequestV1.model_validate(payload)


class IssuerClassificationSnapshotSourcePort(Protocol):
    def retained_sources(
        self, request: IssuerClassificationRequestV1, snapshot: SourceSnapshotV1
    ) -> tuple[RetainedSourceV1, ...]: ...


class IssuerMarketPreparationEvidenceV1(StrictModel):
    protocol: Literal["issuer-market-preparation-v1"] = "issuer-market-preparation-v1"
    request: IssuerMarketPreparationRequestV1
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_issue_codes: tuple[str, ...]
    admissions: tuple[SourceAdmissionV1, ...]
    classification: IssuerClassificationEvidenceV1
    country_mapping: IssuerCountryCrosswalkEvidenceV1
    industry_mapping: IndustryCrosswalkEvidenceV1
    market: AutomaticMarketPolicyEvidenceV1

    @model_validator(mode="after")
    def exact_lineage(self) -> IssuerMarketPreparationEvidenceV1:
        if self.source_issue_codes != tuple(sorted(set(self.source_issue_codes))):
            raise ValueError("issuer market source issues must be canonical")
        digests = tuple(item.output_digest for item in self.admissions)
        if digests != tuple(sorted(set(digests))):
            raise ValueError("issuer market admissions must be canonical")
        if (
            self.classification.request != self.request.classification_request
            or self.classification.provider_id
            != self.request.classification_provider_id
            or self.country_mapping.classification_digest
            != self.classification.output_digest
            or self.industry_mapping.classification_digest
            != self.classification.output_digest
            or self.country_mapping.policy_digest
            != sha256_digest(self.request.country_policy)
            or self.industry_mapping.policy_digest
            != sha256_digest(self.request.industry_policy)
            or self.market.source_revision != self.request.source_revision
            or self.market.plan_decision.classification_digest
            != self.classification.output_digest
            or self.market.plan_decision.country_mapping_digest
            != self.country_mapping.output_digest
            or self.market.plan_decision.industry_mapping_digest
            != self.industry_mapping.output_digest
            or self.market.plan_decision.policy != self.request.reference_policy
            or self.market.decision.policy != self.request.market_policy
        ):
            raise ValueError("issuer market evidence differs from its exact inputs")
        # Bind the retained admissions to the same existing evaluator as serving.
        expected = build_automatic_market_policy_evidence(
            source_revision=self.request.source_revision,
            plan_decision=self.market.plan_decision,
            policy=self.request.market_policy,
            admissions=self.admissions,
        )
        if self.market != expected:
            raise ValueError("issuer market decision differs from its admissions")
        plan = build_issuer_market_reference_plan(
            self.classification,
            country_mapping=self.country_mapping,
            industry_mapping=self.industry_mapping,
            policy=self.request.reference_policy,
            policy_id=self.request.market_policy.terminal_growth_plan.policy_id,
        )
        if self.market.plan_decision != plan:
            raise ValueError("issuer market plan differs from its classification joins")
        return self

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.source_issue_codes) | set(self.market.decision.issue_codes))
        )

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def release_refs(self) -> tuple[ArtifactRefV1, ...]:
        """Prepared evidence references grant no deployment-policy authority."""
        if self.issue_codes:
            return ()
        plan = self.market.plan_decision.plan
        assert plan is not None
        return tuple(
            ArtifactRefV1(
                artifact_id=f"{prefix}:{sha256_digest(value)}",
                content_hash=sha256_digest(value),
                media_type="application/json",
                role=role,
            )
            for prefix, value, role in (
                ("issuer-market-reference-plan", plan, MARKET_REFERENCE_PLAN_ROLE),
                (
                    "issuer-terminal-growth-plan",
                    self.request.market_policy.terminal_growth_plan,
                    TERMINAL_GROWTH_PLAN_ROLE,
                ),
                ("automatic-market-policy", self.market, AUTOMATIC_MARKET_POLICY_ROLE),
                ("issuer-market-preparation", self, self.protocol),
            )
        )


class IssuerMarketPreparation:
    """Coordinate typed sources and policies without source clients or formulas."""

    def __init__(
        self,
        *,
        classification_provider: IssuerClassificationProviderPort,
        classification_sources: IssuerClassificationSnapshotSourcePort,
        country_provider: CountryCrosswalkProviderPort,
        industry_provider: ClassificationCrosswalkProviderPort,
        artifacts: AdmissionArtifactWriter,
    ) -> None:
        self._classification_provider = classification_provider
        self._classification_sources = classification_sources
        self._country_provider = country_provider
        self._industry_provider = industry_provider
        self._artifacts = artifacts

    def execute(
        self,
        request: IssuerMarketPreparationRequestV1,
        *,
        snapshot: SourceSnapshotV1,
        admissions: tuple[SourceAdmissionV1, ...],
    ) -> tuple[IssuerMarketPreparationEvidenceV1, ArtifactPublicationV1]:
        request = IssuerMarketPreparationRequestV1.model_validate_json(
            request.model_dump_json()
        )
        snapshot = SourceSnapshotV1.model_validate_json(snapshot.model_dump_json())
        if (
            request.classification_provider_id
            != self._classification_provider.provider_id
        ):
            raise ValueError("issuer market classification provider is not configured")
        source_issues: set[str] = set()
        sources: tuple[RetainedSourceV1, ...] = ()
        if (
            snapshot.identity.issuer_id != request.classification_request.issuer_id
            or snapshot.valuation_timestamp
            != request.classification_request.valuation_at
            or snapshot.identity.currency != request.market_policy.currency
        ):
            source_issues.add("ISSUER_MARKET_SNAPSHOT_CONTEXT_MISMATCH")
        else:
            try:
                sources = self._classification_sources.retained_sources(
                    request.classification_request, snapshot
                )
            except SnapshotError as error:
                if error.retryable:
                    raise
                source_issues.add(error.code)
        classification = reproduce_issuer_classification(
            self._classification_provider,
            request=request.classification_request,
            sources=sources,
        )
        country = apply_country_crosswalk(
            classification,
            policy=request.country_policy,
            provider=self._country_provider,
        )
        industry = apply_industry_crosswalk(
            classification,
            policy=request.industry_policy,
            provider=self._industry_provider,
        )
        plan = build_issuer_market_reference_plan(
            classification,
            country_mapping=country,
            industry_mapping=industry,
            policy=request.reference_policy,
            policy_id=request.market_policy.terminal_growth_plan.policy_id,
        )
        ordered_admissions = tuple(
            sorted(
                {
                    item.output_digest: SourceAdmissionV1.model_validate_json(
                        item.model_dump_json()
                    )
                    for item in admissions
                }.values(),
                key=lambda item: item.output_digest,
            )
        )
        market = build_automatic_market_policy_evidence(
            source_revision=request.source_revision,
            plan_decision=plan,
            policy=request.market_policy,
            admissions=ordered_admissions,
        )
        result = IssuerMarketPreparationEvidenceV1(
            request=request,
            snapshot_id=snapshot.snapshot_id,
            snapshot_manifest_digest=snapshot.manifest_digest,
            source_issue_codes=tuple(sorted(source_issues)),
            admissions=ordered_admissions,
            classification=classification,
            country_mapping=country,
            industry_mapping=industry,
            market=market,
        )
        dependencies = tuple(
            sorted(
                {
                    request.digest,
                    snapshot.manifest_digest,
                    *(item.content_sha256 for item in classification.source_artifacts),
                    *(item.output_digest for item in ordered_admissions),
                }
            )
        )
        for prefix, value in (
            ("issuer-market-preparation-request", request),
            ("issuer-classification", classification),
            ("issuer-country-crosswalk", country),
            ("industry-crosswalk", industry),
            ("issuer-market-reference-plan-decision", plan),
            ("automatic-market-policy", market),
            ("issuer-terminal-growth-plan", request.market_policy.terminal_growth_plan),
        ):
            self._artifacts.put_with_receipt(f"{prefix}:{sha256_digest(value)}", value)
        if plan.plan is not None:
            self._artifacts.put_with_receipt(
                f"issuer-market-reference-plan:{sha256_digest(plan.plan)}",
                plan.plan,
            )
        publication = self._artifacts.put_with_receipt(
            f"issuer-market-preparation:{result.digest}", result, dependencies
        )
        return result, publication
