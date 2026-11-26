"""Typed application use cases assembled by the HTTP composition root."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from hashlib import sha256
import re
from typing import Any, overload

from pydantic import model_validator

from ..conditional_revision import (
    REVISION_PREFIX,
    FORWARD_REVIEW_PREFIX,
    ConditionalRevisionError,
    ConditionalRevisionForbidden,
    ConditionalRevisionSelectorV1,
    RevisionActor,
    bind_revision,
    issue_revision,
    read_revision,
    read_forward_review,
    retain_forward_review,
    validate_revision_forward_review,
    revision_selector,
)
from ..forward_evidence import (
    ForwardEvidenceReviewRefV1,
    ForwardEvidenceReviewRequestV1,
    ForwardEvidenceReviewResponseV1,
)
from ..calculator import (
    CalculationRefusal,
    calculate,
    validate,
    with_calculation_result_hash,
)
from ..valuation_diagnostics import timed_valuation_stage, valuation_stage
from ..contracts import (
    ArtifactReferenceV1,
    CanonicalFactV1,
    CalculationArtifactV1,
    CalculationEvidenceV1,
    CalculationTraceV1,
    ConditionalRevisionRefV1,
    FactsReadRequestV1,
    FactsReadResponseV1,
    FiscalPeriodSelectorV1,
    PolicyValuationInputV1,
    ProvenanceInputV1,
    QualityStatus,
    ResolvedFiscalPeriodV1,
    SnapshotResolutionRequestV1,
    SnapshotResolutionV1,
    SourceSnapshotV1,
    TraceV1,
    UncertaintyV1,
    ValidationResponseV1,
    ValuationEvidenceReadRequestV1,
    ValuationEvidenceReadResponseV1,
    ValuationInputV1,
)
from ..data_releases import (
    ActiveDataReleaseWithManifestV1,
    ArtifactRefV1,
    DataReleaseActivationCommandV1,
    DataReleaseActivationRequestV1,
    DataReleaseCandidateReceiptV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseVerificationV1,
    ReleaseResolutionCacheKeyV1,
)
from ..artifact_evidence import (
    EvidenceArtifactReader,
    read_retained_artifact,
    retained_artifact_operation,
)
from ..mapping_input_storage import (
    mapping_input_report_dependency,
    require_mapping_report_record,
)
from ..facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    canonical_fact_digest,
    resolve_canonical_facts,
    verify_accounting_role_evidence,
)
from ..equity_award_evidence import (
    load_release_dilution_evidence,
    load_release_conditional_quote,
)
from ..equity_dilution import DilutionError
from ..quote_providers import QuoteSourceProviderPort
from ..macro_series import MacroSeriesProviderPort
from ..market_reference import MarketReferenceProviderPort
from ..source_admission import SourceAdmissionV1, SourceUsePolicyV1
from ..source_admission_evidence import load_release_source_admissions
from ..market_source_selection import MarketSourceError, verify_observed_market_inputs
from ..market_reference_evidence import load_release_market_reference_selection
from ..automatic_market_policy_evidence import load_release_automatic_market_policy
from ..market_reference_selection import (
    IssuerMarketReferenceSelectionV1,
    MarketReferenceSelectionError,
)
from ..terminal_growth import TerminalGrowthSelectionV1
from ..terminal_growth_evidence import load_release_terminal_growth_selection
from ..industry_capital import verify_industry_capital_policy
from ..fiscal_periods import resolve_fiscal_periods
from ..governance import ModelInventory
from ..history_composition import verify_history_components
from ..operations import (
    OperationalMetrics,
    OperationsConfig,
    ServiceError,
    guard_calculation_budget,
    guard_execution_deadline,
)
from ..policies import (
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    resolve_policy,
    resolve_policy_overrides,
)
from ..replay import (
    ArtifactRecordV1,
    CacheLifecycle,
    ReplayEnvelopeV1,
    ReplayReportV1,
    replay_manifest,
)
from ..serialization import canonical_bytes, is_digest, sha256_digest
from ..original_preparation import OriginalPreparation
from ..statement_contracts import (
    AnnualStatementsReadRequestV1,
    AnnualStatementsReadResponseV1,
)
from ..statement_releases import (
    read_statement_release,
    verify_statement_release_membership,
)
from ..snapshots import (
    ContentAddressedStore,
    SnapshotError,
    SnapshotRepository,
)
from ..uncertainty import (
    MonteCarloRequestV1,
    ScenarioV1,
    SensitivityRequestV1,
    UncertaintyEvidenceV1,
    UncertaintyReportV1,
    is_service_owned_monte_carlo,
    run_uncertainty,
    validate_uncertainty_controls,
)
from ..valuation_preparation import (
    CONDITIONAL_FORECAST_COMPOSER_VERSION,
    CONDITIONAL_REINVESTMENT_COMPOSER_VERSION,
    ApprovedMarketPolicyInputsV1,
    AutomaticValuationPreparationV1,
    ManualValuationOverrideRequestV1,
    apply_manual_override,
    prepare_automatic_valuation,
)
from ..valuation_requirements import (
    select_released_facts,
)
from ..valuation_release_inputs import (
    automatic_release_model,
    valuation_release_conditional_capital,
    valuation_release_requirements,
    valuation_release_working_capital_inputs,
)
from ..conditional_reinvestment_release import (
    valuation_release_conditional_reinvestment,
)


from ..fiscal_read_contracts import FiscalReadRequestV1, FiscalReadResultV1
from ..fiscal_release_contracts import ActiveFiscalReleaseV1, FiscalReleaseManifestV1
from ..fiscal_releases import FiscalReleaseReader
from ..publication_codec import ActivePublication, active_publication
from collections.abc import Callable

from ..forecast_timeline import ForecastTimelineError, verify_forecast_timeline_sources


class UncertaintyRequestV1(ValuationInputV1):
    """Valuation input with caller-owned uncertainty controls."""

    scenarios: tuple[ScenarioV1, ...] = ()
    sensitivity: tuple[SensitivityRequestV1, ...] = ()
    monte_carlo: MonteCarloRequestV1 | None = None

    @model_validator(mode="after")
    def validate_digest(self) -> UncertaintyRequestV1:
        payload = self.model_dump(
            exclude={
                "input_digest",
            }
        )
        computed = sha256_digest(payload)
        if self.input_digest is not None and (
            not is_digest(self.input_digest) or self.input_digest != computed
        ):
            raise ValueError("input_digest does not match complete uncertainty request")
        return self

    def base_input(self) -> ValuationInputV1:
        payload = self.model_dump(exclude={"scenarios", "sensitivity", "monte_carlo"})
        payload["input_digest"] = None
        return ValuationInputV1.model_validate(payload)

    def with_digest(self) -> UncertaintyRequestV1:
        payload = self.model_dump(exclude={"input_digest"})
        return self.model_copy(update={"input_digest": sha256_digest(payload)})


def _approved_market_policy(
    policy: PolicyRecordV1 | None,
    *,
    valuation_timestamp: datetime | None = None,
    currency: str | None = None,
    source_admissions: tuple[SourceAdmissionV1, ...] = (),
    reference_selection: IssuerMarketReferenceSelectionV1 | None = None,
    terminal_selection: TerminalGrowthSelectionV1 | None = None,
) -> ApprovedMarketPolicyInputsV1 | None:
    """Translate a complete released market policy into preparation evidence."""

    if policy is None or policy.market_inputs is None:
        return None
    market_inputs = policy.market_inputs
    if valuation_timestamp is not None and any(
        item.available_at > valuation_timestamp for item in market_inputs.evidence
    ):
        return None
    observed_traces: dict[str, TraceV1] = {}
    try:
        industry_traces = verify_industry_capital_policy(
            market_inputs, reference_selection
        )
    except MarketReferenceSelectionError as error:
        raise MarketSourceError(error.code, str(error)) from error
    if any(item.method == "observed_source" for item in market_inputs.evidence):
        if valuation_timestamp is None or currency is None:
            raise MarketSourceError(
                "MARKET_RATE_CONTEXT_MISSING",
                "observed market inputs require valuation time and currency",
            )
        observed_traces = verify_observed_market_inputs(
            market_inputs,
            admissions=source_admissions,
            valuation_at=valuation_timestamp,
            currency=currency,
            reference_selection=reference_selection,
        )

    def trace_for(role: str) -> TraceV1:
        if role == "terminal_growth" and terminal_selection is not None:
            return terminal_selection.trace
        if role in industry_traces:
            return industry_traces[role]
        if role in observed_traces:
            return observed_traces[role]
        evidence = next(
            (item for item in market_inputs.evidence if item.role == role), None
        )
        if evidence is None:
            raise ValueError(f"market policy evidence is missing {role}")
        return TraceV1(
            source_refs=(evidence.content_hash,),
            source_ids=(evidence.source_id,),
            source_uris=(evidence.source_uri,),
            source_versions=(evidence.source_version,),
            terms_references=(evidence.terms_reference,),
            as_of=evidence.as_of,
            available_at=evidence.available_at,
            captured_at=evidence.captured_at,
            description=evidence.rationale,
        )

    evidence = {
        field: trace_for(field)
        for field in (
            "risk_free_rate",
            "beta",
            "equity_risk_premium",
            "pre_tax_cost_of_debt",
            "debt_weight",
            "equity_weight",
            "terminal_growth",
        )
    }
    return ApprovedMarketPolicyInputsV1(
        policy_version=policy.policy_version,
        capital_weight_basis=market_inputs.capital_weight_basis,
        risk_free_rate=market_inputs.risk_free_rate,
        beta=market_inputs.beta,
        equity_risk_premium=market_inputs.equity_risk_premium,
        pre_tax_cost_of_debt=market_inputs.pre_tax_cost_of_debt,
        debt_weight=market_inputs.debt_weight,
        equity_weight=market_inputs.equity_weight,
        terminal_growth=market_inputs.terminal_growth,
        evidence=evidence,
        evidence_methods={item.role: item.method for item in market_inputs.evidence},
    )


def normalize_uncertainty_payload(raw: Mapping[str, object]) -> dict[str, object]:
    """Fold transport wrappers into the canonical uncertainty group before decode."""

    data = dict(raw)
    raw_uncertainty = data.get("uncertainty")
    if raw_uncertainty and not isinstance(raw_uncertainty, Mapping):
        raise ValueError("uncertainty must be an object")
    uncertainty = dict(raw_uncertainty) if isinstance(raw_uncertainty, Mapping) else {}
    monte_carlo = data.get("monte_carlo")
    if isinstance(monte_carlo, Mapping):
        monte_spec = monte_carlo.get("uncertainty")
        if isinstance(monte_spec, Mapping):
            if uncertainty.get("mode") not in {None, "none", "monte_carlo"}:
                raise ValueError("uncertainty controls disagree with monte_carlo")
            uncertainty = {**uncertainty, **dict(monte_spec), "mode": "monte_carlo"}
    for field in ("scenarios", "sensitivity"):
        if field in data:
            existing = uncertainty.get(field)
            if existing not in (None, (), []) and existing != data[field]:
                raise ValueError(f"uncertainty controls disagree for {field}")
            uncertainty[field] = data[field]
    data["uncertainty"] = uncertainty
    return data


def _snapshot_error(error: SnapshotError) -> ServiceError:
    if error.code in {
        "ACCOUNTING_ROLE_MAPPING_MISMATCH",
        "ACCOUNTING_ROLE_INTEGRITY_MISMATCH",
    }:
        return ServiceError(
            error.code,
            "accounting evidence conflicts with its released mapping or original",
            status_code=409,
            retryable=False,
        )
    if error.code in {
        "SNAPSHOT_NOT_FOUND",
        "ARTIFACT_NOT_FOUND",
        "FACT_NOT_FOUND",
    }:
        return ServiceError(
            error.code,
            "requested immutable evidence was not found",
            status_code=404,
            retryable=False,
        )
    if error.code in {"FACT_CONFLICT", "FACT_AMENDMENT_SCOPE_UNKNOWN"}:
        return ServiceError(
            error.code,
            "canonical fact selection is not verified for this snapshot",
            status_code=422,
            retryable=False,
        )
    return ServiceError(
        error.code,
        "immutable evidence is temporarily unavailable",
        status_code=503,
        retryable=error.retryable or error.code.endswith("UNAVAILABLE"),
    )


def _policy_error(error: PolicyError) -> ServiceError:
    if error.code == "POLICY_NOT_FOUND":
        status_code = 404
        retryable = False
    elif error.code in {
        "POLICY_AMBIGUOUS",
        "INPUT_DIGEST_MISMATCH",
    }:
        status_code = 409
        retryable = False
    elif error.code == "POLICY_UNAVAILABLE" or error.code.startswith("METADATA_"):
        status_code = 503
        retryable = True
    else:
        status_code = 422
        retryable = False
    return ServiceError(
        error.code,
        str(error),
        status_code=status_code,
        retryable=retryable,
    )


def _data_release_error(error: DataReleaseError) -> ServiceError:
    if error.code in {
        "DATA_RELEASE_POINTER_CONFLICT",
        "DATA_RELEASE_IDEMPOTENCY_CONFLICT",
        "DATA_RELEASE_IMMUTABLE",
        "DATA_RELEASE_SNAPSHOT_MISMATCH",
        "DATA_RELEASE_FACT_MISMATCH",
    }:
        status_code = 409
    elif error.code in {
        "DATA_RELEASE_CANDIDATE_UNVERIFIED",
        "DATA_RELEASE_VERIFICATION_MISMATCH",
        "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID",
        "DATA_RELEASE_MAPPING_REVIEW_MISMATCH",
        "DATA_RELEASE_MAPPING_REVIEW_SIGNATURE_INVALID",
        "DATA_RELEASE_MAPPING_REVIEW_DUPLICATE",
    }:
        status_code = 422
    elif error.code == "DATA_RELEASE_ROLLBACK_TARGET_INVALID":
        status_code = 422
    else:
        status_code = 503
    return ServiceError(
        error.code,
        "data release operation could not be completed",
        status_code=status_code,
        retryable=error.retryable or status_code == 503,
    )


@dataclass(frozen=True)
class FundamentalApplication:
    """Owns use cases while keeping transport and dependency assembly outside."""

    snapshot_repository: SnapshotRepository | None
    artifact_store: Any
    content_store: ContentAddressedStore | None
    config: OperationsConfig
    metrics: OperationalMetrics
    fact_repository: CanonicalFactRepository | None = None
    metadata_store: Any = None
    require_metadata: bool = False
    policy_registry: PolicyRegistry | None = None
    model_inventory: ModelInventory | None = None
    quote_providers: tuple[QuoteSourceProviderPort, ...] = ()
    macro_providers: tuple[MacroSeriesProviderPort, ...] = ()
    reference_providers: tuple[MarketReferenceProviderPort, ...] = ()
    source_use_policy: SourceUsePolicyV1 | None = None
    statement_originals: OriginalPreparation | None = None
    fiscal_reader_factory: Callable[[], FiscalReleaseReader] | None = None
    release_cache: CacheLifecycle = dataclass_field(
        default_factory=lambda: CacheLifecycle(max_entries=256),
        repr=False,
        compare=False,
    )

    @property
    def ready(self) -> bool:
        return (
            self.snapshot_repository is not None
            and self.artifact_store is not None
            and self.content_store is not None
            and self.fact_repository is not None
            and self.config.auth_ready
            and (
                not self.require_metadata
                or (
                    self.metadata_store is not None
                    and bool(self.metadata_store.ready)
                    and self.model_inventory is not None
                    and self.model_inventory.trust_roots_configured
                )
            )
        )

    @timed_valuation_stage("release.fact_references")
    def _verify_fact_references(self, value: ValuationInputV1) -> None:
        if self.snapshot_repository is None or self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "canonical fact dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        snapshot = self.snapshot(value.valuation_context.data_snapshot_id)
        source_hashes = {record.content_hash for record in snapshot.source_records}
        facts = []
        for fact_id in value.historical_facts:
            try:
                fact = self.fact_repository.get(fact_id)
            except SnapshotError as error:
                raise ServiceError(
                    "FACT_NOT_FOUND",
                    "a requested canonical fact is unavailable",
                    status_code=404,
                    retryable=False,
                ) from error
            if (
                fact.issuer_id != snapshot.identity.issuer_id
                or fact.security_id not in {None, snapshot.identity.security_id}
                or getattr(fact.quality, "value", fact.quality) != "verified"
                or fact.available_at > value.valuation_context.valuation_timestamp
                or fact.source.content_hash not in source_hashes
            ):
                raise ServiceError(
                    "FACT_PROVENANCE_MISMATCH",
                    "a requested canonical fact does not belong to the selected "
                    "snapshot",
                    status_code=422,
                    retryable=False,
                )
            facts.append(fact)
        forecast = value.assumptions.forecast
        if forecast is not None and forecast.timeline is not None:
            try:
                verify_forecast_timeline_sources(
                    forecast.timeline,
                    facts,
                    valuation_timestamp=value.valuation_context.valuation_timestamp,
                    horizon=len(forecast.revenue_growth),
                    base_revenue=forecast.base_revenue,
                )
            except ForecastTimelineError as error:
                raise ServiceError(
                    error.code, str(error), status_code=422, retryable=False
                ) from error
        release_manifest = self._data_release_manifest(
            value.valuation_context.data_release_manifest_digest
        )
        if release_manifest is not None:
            self._verify_release_snapshot_and_facts(
                release_manifest,
                snapshot,
                tuple(facts),
                required_fields=(),
            )

    @overload
    def _data_release_manifest(self, manifest_digest: str) -> DataReleaseManifestV1: ...

    @overload
    def _data_release_manifest(
        self, manifest_digest: str | None
    ) -> DataReleaseManifestV1 | None: ...

    def _data_release_manifest(
        self, manifest_digest: str | None
    ) -> DataReleaseManifestV1 | None:
        if manifest_digest is None:
            if self.require_metadata:
                raise ServiceError(
                    "DATA_RELEASE_MANIFEST_REQUIRED",
                    "production requests require a pinned data release manifest",
                    status_code=422,
                    retryable=False,
                )
            return None
        if self.metadata_store is None:
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        manifest_reader = getattr(
            self.metadata_store, "get_data_release_manifest", None
        )
        if not callable(manifest_reader):
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            manifest = manifest_reader(manifest_digest)
        except DataReleaseError as error:
            raise ServiceError(
                error.code,
                "release metadata is temporarily unavailable",
                status_code=503,
                retryable=error.retryable,
            ) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error
        if manifest is None:
            raise ServiceError(
                "DATA_RELEASE_NOT_FOUND",
                "the pinned data release manifest is unavailable",
                status_code=404,
                retryable=False,
            )
        if not isinstance(manifest, DataReleaseManifestV1):
            raise ServiceError(
                "DATA_RELEASE_PURPOSE_MISMATCH",
                "this operation requires a canonical data release",
                status_code=422,
                retryable=False,
            )
        if manifest.manifest_digest != manifest_digest:
            raise ServiceError(
                "DATA_RELEASE_MANIFEST_MISMATCH",
                "the stored data release does not match the requested digest",
                status_code=409,
                retryable=False,
            )
        return manifest

    @timed_valuation_stage("release.current_artifacts")
    def _verify_current_release_artifacts(
        self, manifest: DataReleaseManifestV1, *, deadline_at: datetime | None = None
    ) -> None:
        """Re-check every retained release dependency before serving valuation.

        Canary validation establishes that a candidate was publishable. Serving
        must also observe later invalidation or metadata substitution; otherwise
        retained snapshot/fact rows could outlive the evidence that authorized
        them. This boundary only reads the pinned bytes and current metadata. The
        domain consumers below continue to validate their own evidence semantics.
        """
        if self.artifact_store is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "release dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        verification_reader = getattr(
            self.metadata_store, "get_data_release_verification", None
        )
        if not callable(verification_reader):
            raise DataReleaseError(
                "DATA_RELEASE_VERIFICATION_UNAVAILABLE",
                "release dependency verification is unavailable",
            )
        guard_execution_deadline(deadline_at)
        try:
            verification = verification_reader(manifest.manifest_digest)
        except DataReleaseError:
            raise
        except Exception as error:  # pragma: no cover - adapter boundary
            raise DataReleaseError(
                "DATA_RELEASE_VERIFICATION_UNAVAILABLE",
                "release dependency verification is unavailable",
            ) from error
        if (
            not isinstance(verification, DataReleaseVerificationV1)
            or verification.manifest_digest != manifest.manifest_digest
        ):
            raise DataReleaseError(
                "DATA_RELEASE_VERIFICATION_MISMATCH",
                "release dependency verification differs from its manifest",
            )
        refs = [
            *manifest.taxonomy_refs,
            *manifest.artifact_refs,
            *verification.evidence_refs,
            *(
                ref
                for review in verification.mapping_reviews
                for ref in review.evidence_refs
            ),
        ]
        with retained_artifact_operation(
            self.artifact_store, tuple(ref.artifact_id for ref in refs)
        ) as artifacts:
            self._verify_retained_release_artifacts(
                artifacts, refs, deadline_at=deadline_at
            )
        guard_execution_deadline(deadline_at)

    @staticmethod
    def _verify_retained_release_artifacts(
        artifacts: EvidenceArtifactReader,
        refs: list[ArtifactRefV1],
        *,
        deadline_at: datetime | None = None,
    ) -> None:
        seen: dict[str, tuple[str, str]] = {}
        report_dependencies: dict[str, tuple[str, ...]] = {}
        expanded_inputs: set[str] = set()
        for reference in refs:
            guard_execution_deadline(deadline_at)
            identity = (reference.content_hash, reference.media_type)
            previous = seen.get(reference.artifact_id)
            if previous is not None and previous != identity:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_REFERENCE_CONFLICT",
                    "release references one artifact ID with different content",
                )
            mapping_input = reference.role in {
                "automatic-mapping-input-v1",
                "automatic-mapping-batch-input-v1",
            }
            try:
                if (
                    previous is not None
                    and reference.artifact_id in report_dependencies
                ):
                    require_mapping_report_record(
                        artifacts.get(reference.artifact_id),
                        reference,
                        report_dependencies[reference.artifact_id],
                    )
                if previous is not None and (
                    not mapping_input or reference.artifact_id in expanded_inputs
                ):
                    continue
                seen[reference.artifact_id] = identity
                raw = read_retained_artifact(
                    artifacts,
                    reference,
                    dependency_hashes=report_dependencies.get(reference.artifact_id),
                )
            except DataReleaseError:
                raise
            except Exception as error:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_UNAVAILABLE",
                    f"release artifact {reference.artifact_id} is unavailable",
                ) from error
            if sha256(raw).hexdigest() != reference.content_hash:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_HASH_MISMATCH",
                    f"release artifact {reference.artifact_id} failed hash verification",
                )
            if mapping_input:
                expanded_inputs.add(reference.artifact_id)
                dependency = mapping_input_report_dependency(raw)
                if dependency is not None:
                    report_ref, expected = dependency
                    previous_dependencies = report_dependencies.setdefault(
                        report_ref.artifact_id, expected
                    )
                    if previous_dependencies != expected:
                        raise DataReleaseError(
                            "MAPPING_ORIGINAL_ARTIFACT_MISMATCH",
                            "shared mapping report has conflicting source dependencies",
                        )
                    refs.append(report_ref)
        guard_execution_deadline(deadline_at)

    def publish_data_release_candidate(
        self, manifest: DataReleaseManifestV1, verification: DataReleaseVerificationV1
    ) -> DataReleaseCandidateReceiptV1:
        if self.metadata_store is None:
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            self.metadata_store.publish_data_release_candidate(manifest, verification)
        except DataReleaseError as error:
            raise _data_release_error(error) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "candidate publication is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error
        return DataReleaseCandidateReceiptV1(
            profile_id=manifest.profile_id,
            release_id=manifest.release_id,
            manifest_digest=manifest.manifest_digest,
            verification_digest=verification.verification_digest,
        )

    def active_data_release(self, profile_id: str) -> ActivePublication:
        if self.metadata_store is None:
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            active = self.metadata_store.get_active_data_release_with_manifest(
                profile_id
            )
        except DataReleaseError as error:
            raise _data_release_error(error) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "active release is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error
        if active is None:
            raise ServiceError(
                "DATA_RELEASE_NOT_ACTIVE",
                "no data release is active for this profile",
                status_code=404,
                retryable=False,
            )
        return self._active_release_response(active)

    @staticmethod
    def _active_release_response(
        active: ActivePublication,
    ) -> ActivePublication:
        if isinstance(active, ActiveFiscalReleaseV1):
            return active
        try:
            return active.model_copy(
                update={"automatic_model": automatic_release_model(active.manifest)}
            )
        except DataReleaseError as error:
            raise _data_release_error(error) from error

    def change_active_data_release(
        self,
        profile_id: str,
        request: DataReleaseActivationRequestV1,
        *,
        actor_id: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime | None = None,
    ) -> ActivePublication:
        if self.metadata_store is None:
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release metadata is unavailable",
                status_code=503,
                retryable=True,
            )
        command = DataReleaseActivationCommandV1(
            profile_id=profile_id,
            manifest_digest=request.manifest_digest,
            expected_revision=request.expected_revision,
            expected_manifest_digest=request.expected_manifest_digest,
            operation=request.operation,
            command_id=request.command_id,
            actor_id=actor_id,
            organization_id=organization_id,
            correlation_id=correlation_id,
            reason=request.reason,
        )
        try:
            candidate = self.metadata_store.get_data_release_manifest(
                command.manifest_digest
            )
            if isinstance(candidate, FiscalReleaseManifestV1):
                if self.fiscal_reader_factory is None:
                    raise ServiceError(
                        "FISCAL_READING_UNAVAILABLE",
                        "fiscal release reader is unavailable",
                        status_code=503,
                        retryable=True,
                    )
                if deadline_at is None:
                    raise ServiceError(
                        "REQUEST_DEADLINE_REQUIRED",
                        "fiscal activation requires an absolute deadline",
                        status_code=422,
                        retryable=False,
                    )
                active = self.fiscal_reader_factory().activate(
                    command, self.metadata_store, deadline_at=deadline_at
                )
            else:
                active = self.metadata_store.compare_and_swap_data_release(command)
            manifest = self.metadata_store.get_data_release_manifest(
                active.manifest_digest
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        except ServiceError:
            raise
        except DataReleaseError as error:
            raise _data_release_error(error) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "DATA_RELEASE_UNAVAILABLE",
                "release activation is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error
        if manifest is None:
            raise ServiceError(
                "DATA_RELEASE_NOT_FOUND",
                "activated release manifest is unavailable",
                status_code=503,
                retryable=True,
            )
        return self._active_release_response(active_publication(active, manifest))

    @timed_valuation_stage("release.snapshot_facts")
    def _release_snapshot_facts(
        self, manifest: DataReleaseManifestV1, snapshot: SourceSnapshotV1
    ) -> tuple[CanonicalFactV1, ...]:
        assert self.fact_repository is not None
        declared_snapshot = next(
            (
                reference
                for reference in manifest.snapshot_refs
                if reference.snapshot_id == snapshot.snapshot_id
            ),
            None,
        )
        if (
            declared_snapshot is None
            or declared_snapshot.manifest_digest != snapshot.manifest_digest
        ):
            raise ServiceError(
                "DATA_RELEASE_SNAPSHOT_MISMATCH",
                "the snapshot does not match the pinned data release",
                status_code=409,
                retryable=False,
            )
        facts = []
        try:
            for reference in declared_snapshot.facts:
                fact = self.fact_repository.get(reference.fact_id)
                if canonical_fact_digest(fact) != reference.fact_digest:
                    raise ServiceError(
                        "DATA_RELEASE_FACT_MISMATCH",
                        "a canonical fact does not match the pinned data release",
                        status_code=409,
                        retryable=False,
                    )
                facts.append(fact)
        except SnapshotError as error:
            if error.code != "FACT_NOT_FOUND":
                raise _snapshot_error(error) from error
            raise ServiceError(
                "FACT_NOT_FOUND",
                "a release-declared canonical fact is unavailable",
                status_code=404,
                retryable=False,
            ) from error
        return tuple(facts)

    @staticmethod
    def _verify_release_snapshot_and_facts(
        manifest: DataReleaseManifestV1,
        snapshot: SourceSnapshotV1,
        facts: tuple[Any, ...],
        *,
        required_fields: tuple[str, ...],
    ) -> None:
        if not set(required_fields).issubset(manifest.required_fields):
            raise ServiceError(
                "DATA_RELEASE_FIELDS_UNAVAILABLE",
                "the pinned release does not cover all requested fields",
                status_code=422,
                retryable=False,
            )
        declared_snapshot = next(
            (
                reference
                for reference in manifest.snapshot_refs
                if reference.snapshot_id == snapshot.snapshot_id
            ),
            None,
        )
        if (
            declared_snapshot is None
            or declared_snapshot.manifest_digest != snapshot.manifest_digest
        ):
            raise ServiceError(
                "DATA_RELEASE_SNAPSHOT_MISMATCH",
                "the snapshot does not match the pinned data release",
                status_code=409,
                retryable=False,
            )
        declared_facts = {
            fact.fact_id: fact.fact_digest for fact in declared_snapshot.facts
        }
        if any(
            fact.fact_id not in declared_facts
            or canonical_fact_digest(fact) != declared_facts[fact.fact_id]
            for fact in facts
        ):
            raise ServiceError(
                "DATA_RELEASE_FACT_MISMATCH",
                "selected canonical facts do not match the pinned data release",
                status_code=409,
                retryable=False,
            )
        selected_fields = {fact.normalized_field for fact in facts}
        if not set(required_fields).issubset(selected_fields):
            raise ServiceError(
                "DATA_RELEASE_FIELDS_UNAVAILABLE",
                "the pinned release does not contain all requested fields",
                status_code=422,
                retryable=False,
            )

    @timed_valuation_stage("policy.resolve")
    def _resolve_policy(self, value: ValuationInputV1) -> tuple[ValuationInputV1, Any]:
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "no service-owned policy registry is available",
                status_code=503,
                retryable=True,
            )
        try:
            policy = self.policy_registry.select_policy(
                model_id=value.model_id,
                model_version=value.model_version,
                valuation_timestamp=value.valuation_context.valuation_timestamp,
                policy_id=value.policy_id,
                issuer_id=value.identity.issuer_id,
                data_release_manifest_digest=value.valuation_context.data_release_manifest_digest,
            )
            if (
                value.provenance.policy_version is not None
                and value.provenance.policy_version != policy.policy_version
            ):
                raise PolicyError(
                    "POLICY_VERSION_MISMATCH",
                    "request policy version does not match the selected release",
                )
            return resolve_policy(request=value, policy=policy)
        except PolicyError as error:
            raise _policy_error(error) from error
        except ValueError as error:
            raise ServiceError(
                "POLICY_INVALID",
                str(error),
                status_code=422,
                retryable=False,
            ) from error

    def _resolve_policy_overrides(
        self, value: PolicyValuationInputV1
    ) -> tuple[ValuationInputV1, Any]:
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "no service-owned policy registry is available",
                status_code=503,
                retryable=True,
            )
        try:
            policy = self.policy_registry.select_policy(
                model_id=value.model_id,
                model_version=value.model_version,
                valuation_timestamp=value.valuation_context.valuation_timestamp,
                policy_id=value.policy_id,
                issuer_id=value.identity.issuer_id,
                data_release_manifest_digest=value.valuation_context.data_release_manifest_digest,
            )
            return resolve_policy_overrides(request=value, policy=policy)
        except PolicyError as error:
            raise _policy_error(error) from error
        except ValueError as error:
            raise ServiceError(
                "POLICY_INVALID",
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        except Exception as error:  # pragma: no cover - persistence boundary
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "service-owned policy registry is temporarily unavailable",
                status_code=503,
                retryable=True,
            ) from error

    def _validation_response(
        self, value: ValuationInputV1, resolution: Any
    ) -> ValidationResponseV1:
        issue_codes = value.quality.issue_codes
        missing_evidence = value.quality.missing_evidence
        quality_status = value.quality.status
        release_issues = self._model_release_issues(value)
        if release_issues:
            quality_status = QualityStatus.UNSUPPORTED
            issue_codes = (*issue_codes, *release_issues)
            missing_evidence = (
                *missing_evidence,
                "complete_model_source_cohort_challenger_calibration_release",
            )
        else:
            self.snapshot(value.valuation_context.data_snapshot_id)
            self._verify_fact_references(value)
        if resolution.selection_mode == "exploratory_active":
            if quality_status is QualityStatus.VERIFIED:
                quality_status = QualityStatus.PROVISIONAL
            issue_codes = (*issue_codes, "POLICY_NOT_PINNED_EXPLORATORY")
            missing_evidence = (*missing_evidence, "caller_pinned_policy_id")
        assert value.input_digest is not None
        return ValidationResponseV1(
            contract_version="fundamental.v1",
            input=value,
            input_digest=value.input_digest,
            quality_status=quality_status,
            policy_resolution=resolution,
            issue_codes=issue_codes,
            missing_evidence=missing_evidence,
        )

    def _model_release_issues(self, value: ValuationInputV1) -> tuple[str, ...]:
        if value.model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
            return ("MODEL_FAMILY_NOT_RELEASED",)
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "no service-owned model registry is available",
                status_code=503,
                retryable=True,
            )
        model = self.policy_registry.model(value.model_id, value.model_version)
        if model is None:
            return ("MODEL_RELEASE_EVIDENCE_MISSING",)
        issues = []
        if model.lifecycle != "active":
            issues.append("MODEL_NOT_ACTIVE")
        if model.release_manifest is None:
            issues.append("MODEL_RELEASE_EVIDENCE_MISSING")
        if value.model_version == f"{value.model_id}-v3" and (
            self.model_inventory is None
            or not any(
                (current.model_id, current.model_version)
                == (value.model_id, value.model_version)
                and current == model
                for current in self.model_inventory.advertised()
            )
        ):
            issues.append("MODEL_RELEASE_EVIDENCE_MISSING")
        return tuple(issues)

    def _require_released_calculator_model(self, value: ValuationInputV1) -> None:
        issues = self._model_release_issues(value)
        if issues:
            raise ServiceError(
                "MODEL_UNSUPPORTED",
                f"model {value.model_id} is not released: {', '.join(issues)}",
                status_code=422,
                retryable=False,
            )

    @staticmethod
    @timed_valuation_stage("calculation.trace")
    def _trace(
        request: ValuationInputV1,
        result: CalculationArtifactV1,
        snapshot: SourceSnapshotV1,
        resolution: Any,
    ) -> CalculationTraceV1:
        source_hashes = tuple(record.content_hash for record in snapshot.source_records)
        if not is_digest(snapshot.manifest_digest) or any(
            not is_digest(content_hash) for content_hash in source_hashes
        ):
            raise ServiceError(
                "SNAPSHOT_PROVENANCE_INVALID",
                "selected snapshot does not contain verified content hashes",
                status_code=422,
                retryable=False,
            )
        if request.provenance.snapshot_id != snapshot.snapshot_id:
            raise ServiceError(
                "SNAPSHOT_PROVENANCE_MISMATCH",
                "request provenance does not identify the selected snapshot",
                status_code=422,
                retryable=False,
            )
        if not request.historical_facts:
            raise ServiceError(
                "FACT_PROVENANCE_MISSING",
                "calculation evidence requires canonical fact IDs",
                status_code=422,
                retryable=False,
            )
        return CalculationTraceV1(
            valuation_timestamp=request.valuation_context.valuation_timestamp,
            fiscal_period_selector=request.valuation_context.fiscal_period_selector,
            resolved_fiscal_periods=request.valuation_context.resolved_fiscal_periods,
            source_selection_policy=request.valuation_context.source_selection_policy,
            source_selection_policy_version=snapshot.policy_version,
            snapshot_id=snapshot.snapshot_id,
            snapshot_manifest_digest=snapshot.manifest_digest,
            data_release_manifest_digest=(
                request.valuation_context.data_release_manifest_digest
            ),
            fact_ids=tuple(sorted(request.historical_facts)),
            source_content_hashes=tuple(sorted(source_hashes)),
            policy_id=resolution.policy_id,
            policy_version=resolution.policy_version,
            policy_digest=resolution.policy_digest,
            model_id=request.model_id,
            model_version=request.model_version,
            assumptions_digest=sha256_digest(
                request.assumptions.model_dump(mode="json")
            ),
            calculation_version=result.calculation_version,
        )

    @timed_valuation_stage("calculation.persist_evidence")
    def _persist_evidence(
        self,
        request: ValuationInputV1,
        result: CalculationArtifactV1,
    ) -> CalculationArtifactV1:
        if self.artifact_store is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "calculation evidence storage is unavailable",
                status_code=503,
                retryable=True,
            )
        trace = result.trace
        if trace is None or result.policy_resolution is None:
            raise ServiceError(
                "CALCULATION_EVIDENCE_INCOMPLETE",
                "calculation evidence trace is incomplete",
                status_code=422,
                retryable=False,
            )
        # Transport correlation IDs are per request; persisted evidence must be
        # byte-stable so the same deterministic result can be safely retried.
        stable_result = result.model_copy(update={"correlation_id": "persisted"})
        evidence = CalculationEvidenceV1(
            contract_version="fundamental.v1",
            request=request,
            calculation=stable_result,
        )
        evidence_digest = sha256_digest(evidence.model_dump(mode="json"))
        artifact_id = f"calculation-evidence-{evidence_digest}"
        dependency_hashes = (
            result.input_digest,
            trace.snapshot_manifest_digest,
            *(
                (trace.data_release_manifest_digest,)
                if trace.data_release_manifest_digest is not None
                else ()
            ),
            *trace.source_content_hashes,
            trace.policy_digest,
            trace.assumptions_digest,
            *(
                (request.provenance.conditional_revision_ref.content_hash,)
                if request.provenance.conditional_revision_ref is not None
                else ()
            ),
        )
        try:
            record = self.artifact_store.put(
                artifact_id,
                evidence,
                dependency_hashes=dependency_hashes,
                retention="evidence",
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        reference = ArtifactReferenceV1(
            artifact_id=record.artifact_id,
            artifact_type="calculation_evidence",
            content_hash=record.content_hash,
            media_type=record.media_type,
        )
        return with_calculation_result_hash(
            result.model_copy(update={"artifact_references": (reference,)})
        )

    @timed_valuation_stage("uncertainty.persist_evidence")
    def _persist_uncertainty_evidence(
        self,
        result: UncertaintyReportV1,
        request: dict[str, object],
    ) -> UncertaintyReportV1:
        if self.artifact_store is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "uncertainty evidence storage is unavailable",
                status_code=503,
                retryable=True,
            )
        trace = result.base.trace
        if trace is None:
            raise ServiceError(
                "UNCERTAINTY_EVIDENCE_INCOMPLETE",
                "uncertainty evidence requires a complete base trace",
                status_code=422,
                retryable=False,
            )
        stable_base = result.base.model_copy(update={"correlation_id": "persisted"})
        stable_result = result.model_copy(
            update={"base": stable_base, "artifact_references": ()}
        )
        evidence = UncertaintyEvidenceV1(request=request, report=stable_result)
        evidence_digest = sha256_digest(evidence.model_dump(mode="json"))
        artifact_id = f"uncertainty-evidence-{evidence_digest}"
        revision_ref = ProvenanceInputV1.model_validate_json(
            canonical_bytes(request["provenance"])
        ).conditional_revision_ref
        dependencies = (
            result.input_digest,
            result.base.input_digest,
            result.base.result_hash,
            trace.snapshot_manifest_digest,
            *(
                (trace.data_release_manifest_digest,)
                if trace.data_release_manifest_digest is not None
                else ()
            ),
            *trace.source_content_hashes,
            trace.policy_digest,
            trace.assumptions_digest,
            *((revision_ref.content_hash,) if revision_ref is not None else ()),
        )
        try:
            record = self.artifact_store.put(
                artifact_id,
                evidence,
                dependency_hashes=dependencies,
                retention="evidence",
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        reference = ArtifactReferenceV1(
            artifact_id=record.artifact_id,
            artifact_type="uncertainty_evidence",
            content_hash=record.content_hash,
            media_type=record.media_type,
        )
        returned_base = result.base.model_copy(
            update={
                "artifact_references": (
                    *result.base.artifact_references,
                    reference,
                )
            }
        )
        return result.model_copy(
            update={
                "base": returned_base,
                "artifact_references": (reference,),
            }
        )

    def snapshot(self, snapshot_id: str) -> SourceSnapshotV1:
        if self.snapshot_repository is None:
            self.metrics.increment("source_health_failures_total")
            raise ServiceError(
                "source_unavailable",
                "selected immutable snapshot is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            snapshot = self.snapshot_repository.get(snapshot_id)
            verify_history_components(snapshot, self.snapshot_repository)
            return snapshot
        except SnapshotError as error:
            self.metrics.increment("source_health_failures_total")
            raise _snapshot_error(error) from error
        except Exception as error:  # pragma: no cover - defensive provider boundary
            self.metrics.increment("source_health_failures_total")
            raise ServiceError(
                "source_unavailable",
                "selected immutable snapshot is unavailable",
                status_code=503,
                retryable=True,
            ) from error

    def read_fiscal_statements(
        self, request: FiscalReadRequestV1, *, deadline_at: datetime
    ) -> FiscalReadResultV1:
        if self.fiscal_reader_factory is None:
            raise ServiceError(
                "FISCAL_READING_UNAVAILABLE",
                "fiscal release reader is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return self.fiscal_reader_factory().read(request, deadline_at=deadline_at)
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        except DataReleaseError as error:
            raise _data_release_error(error) from error

    def read_annual_statements(
        self,
        request: AnnualStatementsReadRequestV1,
        *,
        deadline_at: datetime | None = None,
    ) -> AnnualStatementsReadResponseV1:
        if (
            self.statement_originals is None
            or self.content_store is None
            or self.snapshot_repository is None
            or self.fact_repository is None
        ):
            raise ServiceError(
                "STATEMENT_READING_UNAVAILABLE",
                "annual statement source dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        manifest = self._data_release_manifest(request.data_release_manifest_digest)
        try:
            self._verify_current_release_artifacts(manifest, deadline_at=deadline_at)
            envelope = read_statement_release(manifest, artifacts=self.artifact_store)
            if envelope is None:
                raise ServiceError(
                    "STATEMENT_RELEASE_REQUIRED",
                    "the pinned release does not contain annual statements",
                    status_code=422,
                    retryable=False,
                )
            if envelope.projection.cutoff_at != request.cutoff_at:
                raise ServiceError(
                    "STATEMENT_CUTOFF_MISMATCH",
                    "the requested cutoff differs from the immutable statement release",
                    status_code=422,
                    retryable=False,
                )
            verification = self.metadata_store.get_data_release_verification(
                manifest.manifest_digest
            )
            if not isinstance(verification, DataReleaseVerificationV1):
                raise DataReleaseError(
                    "DATA_RELEASE_VERIFICATION_UNAVAILABLE",
                    "statement release verification is unavailable",
                )
            verify_statement_release_membership(
                manifest,
                envelope,
                originals=self.statement_originals,
                content=self.content_store,
                snapshots=self.snapshot_repository,
                facts=self.fact_repository,
                mappings=self.metadata_store,
                artifacts=self.artifact_store,
                source_revision=verification.source_revision,
            )
            guard_execution_deadline(deadline_at)
            return AnnualStatementsReadResponseV1(
                contract_version="fundamental.annual-statements.v1",
                data_release_manifest_digest=manifest.manifest_digest,
                statements=envelope.statements,
            )
        except DataReleaseError as error:
            raise _data_release_error(error) from error
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    def read_facts(self, request: FactsReadRequestV1) -> FactsReadResponseV1:
        if self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "canonical fact dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        snapshot = self.snapshot(request.snapshot_id)
        release_manifest = self._data_release_manifest(
            request.data_release_manifest_digest
        )
        try:
            if release_manifest is None:
                facts = self.fact_repository.resolve(
                    snapshot=snapshot,
                    valuation_timestamp=snapshot.valuation_timestamp,
                    required_fields=request.required_fields,
                )
            else:
                facts = resolve_canonical_facts(
                    self._release_snapshot_facts(release_manifest, snapshot),
                    snapshot=snapshot,
                    valuation_timestamp=snapshot.valuation_timestamp,
                    required_fields=request.required_fields,
                )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        if release_manifest is not None:
            self._verify_release_snapshot_and_facts(
                release_manifest,
                snapshot,
                facts,
                required_fields=request.required_fields,
            )
        return FactsReadResponseV1(
            contract_version="fundamental.v1",
            snapshot_id=snapshot.snapshot_id,
            data_release_manifest_digest=request.data_release_manifest_digest,
            snapshot_manifest_digest=snapshot.manifest_digest,
            identity=snapshot.identity,
            valuation_timestamp=snapshot.valuation_timestamp,
            quality_status=snapshot.coverage_status,
            issue_codes=tuple(issue.code for issue in snapshot.issues),
            facts=facts,
        )

    @timed_valuation_stage("release.current_mappings")
    def _current_release_mappings(
        self, manifest: DataReleaseManifestV1
    ) -> tuple[CanonicalMappingV1, ...] | None:
        mapping_reader = getattr(self.metadata_store, "get_mapping", None)
        if not callable(mapping_reader):
            if self.require_metadata:
                raise ServiceError(
                    "DATA_RELEASE_MAPPING_UNAVAILABLE",
                    "release mapping metadata is unavailable",
                    status_code=503,
                    retryable=True,
                )
            return None
        try:
            mappings = tuple(
                mapping_reader(ref.mapping_id) for ref in manifest.mapping_refs
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        if any(
            mapping.decision_id != ref.mapping_id
            or sha256_digest(mapping) != ref.mapping_digest
            or mapping.status != "approved"
            for mapping, ref in zip(mappings, manifest.mapping_refs, strict=True)
        ):
            raise ServiceError(
                "DATA_RELEASE_MAPPING_MISMATCH",
                "a canonical mapping differs from the pinned release",
                status_code=409,
                retryable=False,
            )
        return mappings

    def read_valuation_evidence(
        self, request: ValuationEvidenceReadRequestV1
    ) -> ValuationEvidenceReadResponseV1:
        """Load only the immutable fact IDs declared by a pinned data release."""

        if self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "canonical fact dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        snapshot = self.snapshot(request.snapshot_id)
        manifest = self._data_release_manifest(request.data_release_manifest_digest)
        try:
            profile = valuation_release_requirements(manifest, request.model_id)
        except DataReleaseError as error:
            raise ServiceError(
                error.code, str(error), status_code=422, retryable=False
            ) from error
        facts = self._release_snapshot_facts(manifest, snapshot)

        try:
            working_capital_inputs = valuation_release_working_capital_inputs(
                manifest, snapshot
            )
        except DataReleaseError as error:
            raise ServiceError(
                error.code, str(error), status_code=422, retryable=False
            ) from error

        selection = select_released_facts(
            facts,
            profile=profile,
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
            additional_fact_ids=tuple(
                fact_id for item in working_capital_inputs for fact_id in item.fact_ids
            ),
        )
        missing = set(selection.missing_fields)
        issue_codes = list(selection.issue_codes)
        if not set(profile.required_fact_fields).issubset(manifest.required_fields):
            missing.update(
                set(profile.required_fact_fields) - set(manifest.required_fields)
            )
            issue_codes.append("DATA_RELEASE_FIELDS_UNAVAILABLE")
        if missing and "VALUATION_REQUIRED_FACTS_MISSING" not in issue_codes:
            issue_codes.append("VALUATION_REQUIRED_FACTS_MISSING")
        quality_status = (
            QualityStatus.ABSTAIN
            if missing
            else QualityStatus.DEGRADED
            if issue_codes
            else QualityStatus.PROVISIONAL
        )
        mapping_version = None
        mappings = self._current_release_mappings(manifest)
        if mappings is not None:
            versions = {mapping.mapping_version for mapping in mappings}
            mapping_by_id = {mapping.decision_id: mapping for mapping in mappings}
            if len(versions) != 1 or any(
                fact.mapping_decision_id not in mapping_by_id
                or mapping_by_id[fact.mapping_decision_id].source_concept
                != fact.concept
                or mapping_by_id[fact.mapping_decision_id].normalized_field
                != fact.normalized_field
                for fact in selection.facts
            ):
                raise ServiceError(
                    "DATA_RELEASE_MAPPING_FACT_MISMATCH",
                    "release facts must bind one coherent reviewed mapping version",
                    status_code=409,
                    retryable=False,
                )
            mapping_version = next(iter(versions))
            for fact in selection.facts:
                assert fact.mapping_decision_id is not None
                try:
                    verify_accounting_role_evidence(
                        fact, mapping_by_id[fact.mapping_decision_id], snapshot
                    )
                except SnapshotError as error:
                    raise _snapshot_error(error) from error
        return ValuationEvidenceReadResponseV1(
            contract_version="fundamental.v1",
            snapshot_id=snapshot.snapshot_id,
            data_release_manifest_digest=manifest.manifest_digest,
            snapshot_manifest_digest=snapshot.manifest_digest,
            identity=snapshot.identity,
            valuation_timestamp=snapshot.valuation_timestamp,
            model_id=request.model_id,
            profile_id=profile.profile_id,
            profile_digest=profile.digest,
            quality_status=quality_status,
            issue_codes=tuple(dict.fromkeys(issue_codes)),
            missing_fields=tuple(sorted(missing)),
            rejected_fact_ids=selection.rejected_fact_ids,
            mapping_version=mapping_version,
            facts=selection.facts,
        )

    @timed_valuation_stage("preparation.compose")
    def prepare_valuation(
        self,
        request: ValuationEvidenceReadRequestV1,
        *,
        policy_id: str | None = None,
        deadline_at: datetime | None = None,
    ) -> AutomaticValuationPreparationV1:
        """Prepare one valuation from the pinned release and service policy."""

        guard_execution_deadline(deadline_at)
        evidence = self.read_valuation_evidence(request)
        guard_execution_deadline(deadline_at)
        snapshot = self.snapshot(request.snapshot_id)
        manifest = self._data_release_manifest(request.data_release_manifest_digest)
        assert manifest is not None
        try:
            self._verify_current_release_artifacts(manifest, deadline_at=deadline_at)
            release_model = automatic_release_model(manifest)
            if release_model is not None and release_model.model_id != request.model_id:
                raise DataReleaseError(
                    "DATA_RELEASE_AUTOMATIC_MODEL_MISMATCH",
                    "preparation must use the exact model bound by its release",
                )
        except DataReleaseError as error:
            raise ServiceError(
                error.code, str(error), status_code=422, retryable=False
            ) from error
        working_capital_inputs = valuation_release_working_capital_inputs(
            manifest, snapshot
        )
        declared_input_policy = manifest.valuation_working_capital_policy
        if (
            declared_input_policy is not None
            and evidence.mapping_version != declared_input_policy.mapping_version
        ):
            raise ServiceError(
                "DATA_RELEASE_MAPPING_VERSION_MISMATCH",
                "valuation working-capital inputs require the release mapping version",
                status_code=422,
                retryable=False,
            )
        try:
            source_admissions = load_release_source_admissions(
                self._data_release_manifest(request.data_release_manifest_digest),
                artifacts=self.artifact_store,
                policy=self.source_use_policy,
                macro_providers=self.macro_providers,
                reference_providers=self.reference_providers,
            )
        except (DataReleaseError, SnapshotError, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "SOURCE_ADMISSION_INVALID"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        model_version = (
            release_model.model_version
            if release_model is not None
            else f"{request.model_id}-v2"
        )
        policy = None
        if self.policy_registry is not None:
            try:
                policy = self.policy_registry.select_policy(
                    model_id=request.model_id,
                    model_version=model_version,
                    valuation_timestamp=snapshot.valuation_timestamp,
                    policy_id=policy_id,
                    issuer_id=snapshot.identity.issuer_id,
                    data_release_manifest_digest=manifest.manifest_digest,
                )
            except PolicyError as error:
                raise ServiceError(
                    error.code,
                    "an effective service-owned valuation policy is unavailable",
                    status_code=422,
                    retryable=False,
                ) from error

        policy_id = (
            policy.policy_id
            if policy is not None
            else (f"{request.model_id}-us-gaap-public-v3")
        )
        policy_version = policy.policy_version if policy is not None else "unresolved"
        try:
            load_release_automatic_market_policy(
                self._data_release_manifest(request.data_release_manifest_digest),
                snapshot=snapshot,
                policy=policy,
                admissions=source_admissions,
                artifacts=self.artifact_store,
            )
            reference_selection = load_release_market_reference_selection(
                self._data_release_manifest(request.data_release_manifest_digest),
                snapshot=snapshot,
                policy=policy,
                admissions=source_admissions,
                artifacts=self.artifact_store,
            )
            terminal_selection = load_release_terminal_growth_selection(
                self._data_release_manifest(request.data_release_manifest_digest),
                snapshot=snapshot,
                policy=policy,
                admissions=source_admissions,
                artifacts=self.artifact_store,
            )
            market_policy = _approved_market_policy(
                policy,
                valuation_timestamp=snapshot.valuation_timestamp,
                currency=snapshot.identity.currency,
                source_admissions=source_admissions,
                reference_selection=reference_selection,
                terminal_selection=terminal_selection,
            )
        except (MarketSourceError, DataReleaseError, SnapshotError) as error:
            raise ServiceError(
                error.code, str(error), status_code=422, retryable=False
            ) from error
        try:
            reinvestment = valuation_release_conditional_reinvestment(
                manifest,
                snapshot,
                evidence.facts,
                mapping_version=evidence.mapping_version or "sec-canonical-mapping-v1",
                artifacts=self.artifact_store,
            )
            conditional = valuation_release_conditional_capital(
                manifest,
                snapshot,
                evidence.facts,
                mapping_version=evidence.mapping_version or "sec-canonical-mapping-v1",
            )
            conditional_quote = None
            dilution = None
            if conditional is not None:
                conditional_quote = load_release_conditional_quote(
                    manifest,
                    policy=conditional.policy,
                    snapshot=snapshot,
                    artifacts=self.artifact_store,
                    quote_providers=self.quote_providers,
                    source_use_policy=self.source_use_policy,
                )
            else:
                dilution = load_release_dilution_evidence(
                    manifest,
                    snapshot=snapshot,
                    artifacts=self.artifact_store,
                    released_facts=evidence.facts,
                    quote_providers=self.quote_providers,
                    source_use_policy=self.source_use_policy,
                )
        except (DataReleaseError, DilutionError, SnapshotError, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "DILUTION_EVIDENCE_INVALID"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        guard_execution_deadline(deadline_at)
        preparation = prepare_automatic_valuation(
            evidence.facts,
            snapshot=snapshot,
            model_id=request.model_id,
            model_version=(
                policy.model_version if policy is not None else model_version
            ),
            policy_id=policy_id,
            policy_version=policy_version,
            data_release_manifest_digest=request.data_release_manifest_digest,
            market_policy=market_policy,
            mapping_version=evidence.mapping_version or "sec-canonical-mapping-v1",
            equity_dilution_evidence=dilution,
            working_capital_inputs=working_capital_inputs,
            conditional_capital_policy=conditional.policy
            if conditional is not None
            else None,
            conditional_quote=conditional_quote,
            conditional_reinvestment_policy=reinvestment.policy
            if reinvestment is not None
            else None,
        )
        guard_execution_deadline(deadline_at)
        return preparation

    def _reproduce_conditional_preparation(
        self,
        selector: ConditionalRevisionSelectorV1,
        *,
        deadline_at: datetime | None,
    ) -> AutomaticValuationPreparationV1:
        return self.prepare_valuation(
            ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=selector.snapshot_id,
                data_release_manifest_digest=selector.data_release_manifest_digest,
                model_id=selector.model_id,
            ),
            policy_id=selector.policy_id,
            deadline_at=deadline_at,
        )

    def _revision_dependencies(
        self, automatic: AutomaticValuationPreparationV1
    ) -> tuple[str, ...]:
        selector = revision_selector(automatic)
        manifest = self._data_release_manifest(selector.data_release_manifest_digest)
        if manifest is None or automatic.input is None:
            raise ConditionalRevisionError(
                "revision requires retained release evidence"
            )
        assert automatic.input.input_digest is not None
        assert automatic.input.assumptions.trace is not None
        return tuple(
            sorted(
                {
                    automatic.preparation_digest,
                    automatic.input.input_digest,
                    manifest.manifest_digest,
                    *(ref.content_hash for ref in manifest.artifact_refs),
                    *(
                        ref
                        for ref in automatic.input.assumptions.trace.source_refs
                        if is_digest(ref)
                    ),
                }
            )
        )

    def _recompose_revision(
        self,
        ref: ConditionalRevisionRefV1,
        *,
        revision_actor: RevisionActor | None,
        deadline_at: datetime | None,
        automatic: AutomaticValuationPreparationV1 | None = None,
    ) -> AutomaticValuationPreparationV1:
        if self.artifact_store is None:
            raise ConditionalRevisionError("retained revision storage is unavailable")
        proof = read_revision(
            self.artifact_store, ref, actor=revision_actor, deadline_at=deadline_at
        )
        if automatic is None:
            automatic = self._reproduce_conditional_preparation(
                proof.selector, deadline_at=deadline_at
            )
        validate_revision_forward_review(
            self.artifact_store,
            automatic,
            proof,
            actor=revision_actor,
            deadline_at=deadline_at,
        )
        expected_dependencies = tuple(
            sorted(
                {
                    *self._revision_dependencies(automatic),
                    *(
                        (proof.forward_review_ref.content_hash,)
                        if proof.forward_review_ref is not None
                        else ()
                    ),
                }
            )
        )
        record = self.artifact_store.get(ref.artifact_id)
        if (
            record.dependency_hashes != expected_dependencies
            or record.status != "valid"
        ):
            raise ConditionalRevisionError("revision dependencies are not retained")
        guard_execution_deadline(deadline_at)
        return bind_revision(automatic, proof, ref)

    def review_forward_evidence(
        self,
        request: ForwardEvidenceReviewRequestV1,
        *,
        revision_actor: RevisionActor,
        deadline_at: datetime | None = None,
    ) -> ForwardEvidenceReviewResponseV1:
        if self.artifact_store is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "review evidence storage is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return retain_forward_review(
                self.artifact_store,
                request,
                actor=revision_actor,
                deadline_at=deadline_at,
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        except ValueError as error:
            raise ServiceError(
                "FORWARD_REVIEW_INVALID",
                "review evidence could not be retained",
                status_code=422,
                retryable=False,
            ) from error

    def apply_manual_override(
        self,
        request: ManualValuationOverrideRequestV1,
        *,
        revision_actor: RevisionActor | None = None,
        deadline_at: datetime | None = None,
    ) -> AutomaticValuationPreparationV1:
        try:
            if (
                request.preparation.conditional_operating is not None
                or request.preparation.conditional_capital is not None
            ):
                if revision_actor is None:
                    raise ConditionalRevisionForbidden(
                        "revision requires an authenticated owner"
                    )
                if self.artifact_store is None:
                    raise ConditionalRevisionError(
                        "retained revision storage is unavailable"
                    )
                guard_execution_deadline(deadline_at)
                automatic = self._reproduce_conditional_preparation(
                    revision_selector(request.preparation), deadline_at=deadline_at
                )
                return issue_revision(
                    self.artifact_store,
                    automatic,
                    request,
                    actor=revision_actor,
                    dependency_hashes=self._revision_dependencies(automatic),
                    deadline_at=deadline_at,
                )
            if request.forward_review_ref is not None:
                raise ServiceError(
                    "FORWARD_REVIEW_UNSUPPORTED",
                    "retained forward reviews require a conditional preparation",
                    status_code=422,
                    retryable=False,
                )
            provenance = request.provenance
            if revision_actor is not None:
                provenance = provenance.model_copy(
                    update={"author": revision_actor.subject_id}
                )
            return apply_manual_override(
                request.preparation,
                path=request.path,
                value=request.value,
                provenance=provenance,
            )
        except ConditionalRevisionForbidden as error:
            raise ServiceError(
                "CONDITIONAL_REVISION_FORBIDDEN",
                str(error),
                status_code=403,
                retryable=False,
            ) from error
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        except ValueError as error:
            raise ServiceError(
                "MANUAL_OVERRIDE_INVALID",
                str(error),
                status_code=422,
                retryable=False,
            ) from error

    def policy(self, policy_id: str) -> PolicyRecordV1:
        if self.policy_registry is None:
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "service-owned policy registry is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            policy = self.policy_registry.policy(policy_id)
        except PolicyError as error:
            raise _policy_error(error) from error
        except Exception as error:  # pragma: no cover - defensive persistence boundary
            raise ServiceError(
                "POLICY_UNAVAILABLE",
                "service-owned policy release is unavailable",
                status_code=503,
                retryable=True,
            ) from error
        if policy is None:
            raise ServiceError(
                "POLICY_NOT_FOUND",
                "requested policy release was not found",
                status_code=404,
                retryable=False,
            )
        return policy

    def _series_snapshot_candidates(
        self,
        request: SnapshotResolutionRequestV1,
        active_release: ActiveDataReleaseWithManifestV1 | None,
    ) -> tuple[SourceSnapshotV1, ...]:
        if active_release is None:
            raise ServiceError(
                "SERIES_RELEASE_REQUIRED",
                "series selection requires an active release",
                status_code=422,
                retryable=False,
            )
        identity = request.identity
        if (
            identity.share_class != identity.security_id
            or re.fullmatch(r"[A-Z0-9.-]{1,32}", identity.security_id) is None
        ):
            raise ServiceError(
                "SERIES_KEY_INVALID",
                "series selection requires the opaque selected SEC ticker key",
                status_code=422,
                retryable=False,
            )
        candidates = []
        for ref in active_release.manifest.snapshot_refs:
            snapshot = self.snapshot(ref.snapshot_id)
            if snapshot.manifest_digest != ref.manifest_digest:
                raise ServiceError(
                    "DATA_RELEASE_SNAPSHOT_MISMATCH",
                    "released snapshot identity failed verification",
                    status_code=409,
                    retryable=False,
                )
            if snapshot.valuation_timestamp > request.valuation_timestamp:
                continue
            if any(
                getattr(snapshot.identity, field) != getattr(identity, field)
                for field in (
                    "issuer_id",
                    "security_id",
                    "currency",
                    "domicile",
                    "reporting_basis",
                )
            ):
                continue
            self._release_snapshot_facts(active_release.manifest, snapshot)
            candidates.append(snapshot)
        if len({snapshot.identity.share_class for snapshot in candidates}) > 1:
            raise ServiceError(
                "SERIES_IDENTITY_AMBIGUOUS",
                "the released series does not select one canonical share class",
                status_code=422,
                retryable=False,
            )
        return tuple(
            sorted(
                candidates,
                key=lambda snapshot: (
                    snapshot.valuation_timestamp,
                    snapshot.snapshot_id,
                ),
                reverse=True,
            )
        )

    def resolve_snapshot(
        self, request: SnapshotResolutionRequestV1
    ) -> SnapshotResolutionV1:
        if self.snapshot_repository is None or self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "snapshot resolution dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        active_release: ActiveDataReleaseWithManifestV1 | None = None
        fiscal_selector = request.fiscal_period_selector or FiscalPeriodSelectorV1(
            mode="latest_complete", count=3
        )
        cache_key: str | None = None
        cache_dependencies: tuple[str, ...] = ()
        if request.release_profile_id is None:
            if self.require_metadata:
                raise ServiceError(
                    "DATA_RELEASE_PROFILE_REQUIRED",
                    "production snapshot resolution requires a release profile",
                    status_code=422,
                    retryable=False,
                )
        else:
            if self.metadata_store is None:
                raise ServiceError(
                    "DATA_RELEASE_UNAVAILABLE",
                    "release metadata is unavailable",
                    status_code=503,
                    retryable=True,
                )
            release_reader = getattr(
                self.metadata_store, "get_active_data_release_with_manifest", None
            )
            if not callable(release_reader):
                raise ServiceError(
                    "DATA_RELEASE_UNAVAILABLE",
                    "release metadata is unavailable",
                    status_code=503,
                    retryable=True,
                )
            try:
                active_release = release_reader(request.release_profile_id)
            except DataReleaseError as error:
                raise ServiceError(
                    error.code,
                    "active data release is temporarily unavailable",
                    status_code=503,
                    retryable=error.retryable,
                ) from error
            if active_release is None:
                raise ServiceError(
                    "DATA_RELEASE_NOT_ACTIVE",
                    "no active data release is available for this profile",
                    status_code=503,
                    retryable=True,
                )
            if not isinstance(active_release.manifest, DataReleaseManifestV1):
                raise ServiceError(
                    "DATA_RELEASE_PURPOSE_MISMATCH",
                    "snapshot resolution requires a canonical data release",
                    status_code=422,
                    retryable=False,
                )
            if not set(request.required_fields).issubset(
                active_release.manifest.required_fields
            ):
                raise ServiceError(
                    "DATA_RELEASE_FIELDS_UNAVAILABLE",
                    "the active release does not cover all required fields",
                    status_code=422,
                    retryable=False,
                )

            manifest = active_release.manifest
            identity_digest = sha256_digest(request.identity.model_dump(mode="json"))
            cache_key_model = ReleaseResolutionCacheKeyV1(
                profile_id=manifest.profile_id,
                manifest_digest=manifest.manifest_digest,
                snapshot_refs=manifest.snapshot_refs,
                mapping_refs=manifest.mapping_refs,
                taxonomy_refs=manifest.taxonomy_refs,
                artifact_refs=manifest.artifact_refs,
                parser_version=manifest.parser_version,
                quality_profile_digest=manifest.quality_profile_digest,
                identity_digest=identity_digest,
                identity_selection_policy=request.identity_selection_policy,
                valuation_timestamp=request.valuation_timestamp,
                source_selection_policy=request.source_selection_policy,
                coverage_profile=request.coverage_profile,
                required_fields=request.required_fields,
                fiscal_period_selector_digest=sha256_digest(
                    fiscal_selector.model_dump(mode="json")
                ),
            )
            cache_key = f"data-release-resolution:v1:{cache_key_model.digest()}"
            cache_dependencies = (
                manifest.manifest_digest,
                manifest.quality_profile_digest,
                identity_digest,
                sha256_digest(manifest.parser_version),
                *(ref.manifest_digest for ref in manifest.snapshot_refs),
                *(
                    fact.fact_digest
                    for snapshot_ref in manifest.snapshot_refs
                    for fact in snapshot_ref.facts
                ),
                *(ref.mapping_digest for ref in manifest.mapping_refs),
                *(ref.content_hash for ref in manifest.taxonomy_refs),
                *(ref.content_hash for ref in manifest.artifact_refs),
            )
            cache_status, cached_resolution = self.release_cache.get(cache_key)
            if cache_status == "hit" and isinstance(
                cached_resolution, SnapshotResolutionV1
            ):
                self._release_snapshot_facts(
                    manifest, self.snapshot(cached_resolution.snapshot_id)
                )
                self.metrics.increment("cache_hit_total")
                return cached_resolution
            if cache_status == "hit":
                self.release_cache.invalidate(cache_key)
                cache_status = "stale"
            if cache_status == "stale":
                self.metrics.increment("cache_stale_total")
            else:
                self.metrics.increment("cache_miss_total")

        candidates = (
            self._series_snapshot_candidates(request, active_release)
            if request.identity_selection_policy == "sec-ticker-series-v1"
            else self.snapshot_repository.find(
                identity=request.identity,
                valuation_timestamp=request.valuation_timestamp,
            )
        )
        declared_snapshots = (
            {
                snapshot.snapshot_id: snapshot
                for snapshot in active_release.manifest.snapshot_refs
            }
            if active_release is not None
            else None
        )
        if declared_snapshots is not None:
            candidates = tuple(
                snapshot
                for snapshot in candidates
                if snapshot.snapshot_id in declared_snapshots
            )
        if not candidates:
            raise ServiceError(
                "SNAPSHOT_NOT_FOUND",
                "no immutable snapshot is available for the requested "
                "identity and time",
                status_code=404,
                retryable=False,
            )
        selector_requested = request.fiscal_period_selector is not None
        for snapshot in candidates:
            snapshot = self.snapshot(snapshot.snapshot_id)
            released_facts = (
                self._release_snapshot_facts(active_release.manifest, snapshot)
                if active_release is not None
                else None
            )
            try:
                if released_facts is None:
                    facts = self.fact_repository.resolve(
                        snapshot=snapshot,
                        valuation_timestamp=request.valuation_timestamp,
                        required_fields=request.required_fields,
                    )
                else:
                    facts = resolve_canonical_facts(
                        released_facts,
                        snapshot=snapshot,
                        valuation_timestamp=request.valuation_timestamp,
                        required_fields=request.required_fields,
                    )
            except SnapshotError as error:
                if error.code == "FACT_NOT_FOUND":
                    continue
                raise _snapshot_error(error) from error
            period_resolution = None
            resolved_periods: tuple[ResolvedFiscalPeriodV1, ...] = ()
            if selector_requested:
                if released_facts is None:
                    list_facts = getattr(self.fact_repository, "list", None)
                    if not callable(list_facts):
                        raise ServiceError(
                            "FISCAL_PERIODS_UNAVAILABLE",
                            "the fact repository cannot resolve issuer fiscal periods",
                            status_code=503,
                            retryable=True,
                        )
                    period_facts = list_facts()
                else:
                    period_facts = released_facts
                selection = resolve_fiscal_periods(
                    period_facts,
                    snapshot=snapshot,
                    valuation_timestamp=request.valuation_timestamp,
                    selector=fiscal_selector,
                    required_fields=request.required_fields,
                )
                period_resolution = selection.resolution
                resolved_periods = period_resolution.resolved_periods
                if period_resolution.status != "resolved":
                    raise ServiceError(
                        period_resolution.issue_codes[0],
                        "requested fiscal periods are not fully available as of "
                        "the valuation timestamp",
                        status_code=422,
                        retryable=False,
                    )
                facts = selection.facts
            if active_release is not None:
                self._verify_release_snapshot_and_facts(
                    active_release.manifest,
                    snapshot,
                    facts,
                    required_fields=request.required_fields,
                )
            result = SnapshotResolutionV1(
                identity_selection_policy=request.identity_selection_policy,
                contract_version="fundamental.v1",
                snapshot_id=snapshot.snapshot_id,
                data_release_manifest_digest=(
                    None
                    if active_release is None
                    else active_release.manifest.manifest_digest
                ),
                historical_facts=tuple(fact.fact_id for fact in facts),
                identity=snapshot.identity,
                valuation_timestamp=request.valuation_timestamp,
                snapshot_timestamp=snapshot.valuation_timestamp,
                fiscal_period_selector=fiscal_selector,
                resolved_fiscal_periods=resolved_periods,
                fiscal_period_resolution=period_resolution,
                source_selection_policy=request.source_selection_policy,
                coverage_profile=request.coverage_profile,
                quality=snapshot.coverage_status,
                issue_codes=tuple(issue.code for issue in snapshot.issues),
                provenance={
                    "snapshot_id": snapshot.snapshot_id,
                    "mapping_version": request.source_selection_policy,
                    "parser_version": snapshot.parser_version,
                    "taxonomy_version": snapshot.taxonomy_manifest_id,
                    "policy_version": snapshot.policy_version,
                    "fiscal_period_selector": fiscal_selector.model_dump(mode="json"),
                    "resolved_fiscal_periods": [
                        period.model_dump(mode="json") for period in resolved_periods
                    ],
                    "data_release_manifest_digest": (
                        None
                        if active_release is None
                        else active_release.manifest.manifest_digest
                    ),
                },
            )
            if cache_key is not None:
                self.release_cache.put(
                    cache_key,
                    result,
                    cache_dependencies,
                    ttl_seconds=60,
                )
            return result
        raise ServiceError(
            "FACT_NOT_FOUND",
            "required canonical facts are not available for the requested snapshot",
            status_code=404,
            retryable=False,
        )

    def _read_authorized_artifact(
        self,
        artifact_id: str,
        *,
        revision_actor: RevisionActor | None,
        deadline_at: datetime | None,
    ) -> tuple[ArtifactRecordV1, bytes | None]:
        if self.artifact_store is None:
            raise ServiceError(
                "source_unavailable",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            record = self.artifact_store.get(artifact_id)
            guarded = artifact_id.startswith(
                (
                    REVISION_PREFIX,
                    FORWARD_REVIEW_PREFIX,
                    "calculation-evidence-",
                    "uncertainty-evidence-",
                )
            )
            if not guarded:
                return record, None
            if record.media_type != "application/json":
                raise ConditionalRevisionError(
                    "retained evidence media type is invalid"
                )
            raw = read_retained_artifact(
                self.artifact_store,
                ArtifactRefV1(
                    artifact_id=record.artifact_id,
                    content_hash=record.content_hash,
                    media_type=record.media_type,
                    role="calculation_evidence",
                ),
            )
            if (
                record.media_type != "application/json"
                or sha256(raw).hexdigest() != record.content_hash
            ):
                raise ConditionalRevisionError("retained evidence bytes are invalid")
            if artifact_id.startswith(FORWARD_REVIEW_PREFIX):
                read_forward_review(
                    self.artifact_store,
                    ForwardEvidenceReviewRefV1(
                        artifact_id=artifact_id, content_hash=record.content_hash
                    ),
                    actor=revision_actor,
                    deadline_at=deadline_at,
                )
                return record, raw
            ref: ConditionalRevisionRefV1 | None
            if artifact_id.startswith(REVISION_PREFIX):
                ref = ConditionalRevisionRefV1(
                    artifact_id=artifact_id, content_hash=record.content_hash
                )
            elif artifact_id.startswith("calculation-evidence-"):
                ref = CalculationEvidenceV1.model_validate_json(
                    raw
                ).request.provenance.conditional_revision_ref
            else:
                evidence = UncertaintyEvidenceV1.model_validate_json(raw)
                ref = ValuationInputV1.model_validate_json(
                    canonical_bytes(evidence.request)
                ).provenance.conditional_revision_ref
            if ref is not None:
                self._recompose_revision(
                    ref, revision_actor=revision_actor, deadline_at=deadline_at
                )
                if (
                    artifact_id != ref.artifact_id
                    and ref.content_hash not in record.dependency_hashes
                ):
                    raise ConditionalRevisionError(
                        "derived evidence is not revision bound"
                    )
            guard_execution_deadline(deadline_at)
            return record, raw
        except ConditionalRevisionForbidden as error:
            raise ServiceError(
                "CONDITIONAL_REVISION_FORBIDDEN",
                "evidence requires its authenticated owner",
                status_code=403,
                retryable=False,
            ) from error
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        except (ValueError, DataReleaseError) as error:
            raise ServiceError(
                "ARTIFACT_EVIDENCE_INVALID",
                "retained evidence did not verify",
                status_code=422,
                retryable=False,
            ) from error

    def artifact(
        self,
        artifact_id: str,
        *,
        revision_actor: RevisionActor | None = None,
        deadline_at: datetime | None = None,
    ) -> ArtifactRecordV1:
        record, _ = self._read_authorized_artifact(
            artifact_id, revision_actor=revision_actor, deadline_at=deadline_at
        )
        return record

    def artifact_content(
        self,
        artifact_id: str,
        *,
        revision_actor: RevisionActor | None = None,
        deadline_at: datetime | None = None,
    ) -> tuple[ArtifactRecordV1, bytes]:
        record, raw = self._read_authorized_artifact(
            artifact_id, revision_actor=revision_actor, deadline_at=deadline_at
        )
        if raw is not None:
            return record, raw
        try:
            return record, self.artifact_store.read(artifact_id)
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    def validate_valuation(self, value: ValuationInputV1) -> ValidationResponseV1:
        resolved = validate(value)
        resolved, resolution = self._resolve_policy(resolved)
        return self._validation_response(resolved, resolution)

    def validate_with_policy(
        self, value: PolicyValuationInputV1
    ) -> ValidationResponseV1:
        resolved, resolution = self._resolve_policy_overrides(value)
        return self._validation_response(resolved, resolution)

    def validate_uncertainty(self, value: UncertaintyRequestV1) -> ValidationResponseV1:
        return self.validate_valuation(value.base_input())

    def calculate_valuation(
        self,
        value: ValuationInputV1,
        *,
        correlation_id: str,
        deadline_at: datetime | None = None,
        revision_actor: RevisionActor | None = None,
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        return self._calculate_valuation(
            value,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
            revision_actor=revision_actor,
        )

    def _calculate_valuation(
        self,
        value: ValuationInputV1,
        *,
        correlation_id: str,
        deadline_at: datetime | None = None,
        revision_actor: RevisionActor | None = None,
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        guard_execution_deadline(deadline_at)
        self._require_released_calculator_model(value)
        if value.policy_id is None:
            raise ServiceError(
                "POLICY_ID_REQUIRED",
                "verified calculations require an explicit immutable policy_id",
                status_code=422,
                retryable=False,
            )
        resolved, resolution = self._resolve_policy(value)
        return self._calculate_resolved(
            resolved,
            resolution,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
            revision_actor=revision_actor,
        )

    def calculate_with_policy(
        self,
        value: PolicyValuationInputV1,
        *,
        correlation_id: str,
        deadline_at: datetime | None = None,
        revision_actor: RevisionActor | None = None,
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        guard_execution_deadline(deadline_at)
        resolved, resolution = self._resolve_policy_overrides(value)
        return self._calculate_resolved(
            resolved,
            resolution,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
            revision_actor=revision_actor,
        )

    @timed_valuation_stage("release.conditional_input")
    def _is_released_conditional_input(
        self,
        value: ValuationInputV1,
        *,
        deadline_at: datetime | None = None,
        revision_actor: RevisionActor | None = None,
    ) -> bool:
        manifest = self._data_release_manifest(
            value.valuation_context.data_release_manifest_digest
        )
        reinvestment = bool(manifest and manifest.conditional_reinvestment_policies)
        prefix = "CONDITIONAL_REINVESTMENT" if reinvestment else "CONDITIONAL_CAPITAL"
        tagged = value.provenance.preparation_version in {
            CONDITIONAL_FORECAST_COMPOSER_VERSION,
            CONDITIONAL_REINVESTMENT_COMPOSER_VERSION,
        }
        if manifest is None or not (
            manifest.conditional_capital_policies
            or manifest.conditional_reinvestment_policies
        ):
            if tagged or value.provenance.conditional_revision_ref is not None:
                raise ServiceError(
                    "CONDITIONAL_CAPITAL_RELEASE_MISSING",
                    "conditional composition requires a pinned conditional release",
                    status_code=422,
                    retryable=False,
                )
            return False
        if value.model_id != "fcff_dcf" and value.model_id != "transition_fcff_dcf":
            raise ServiceError(
                f"{prefix}_MODEL_MISMATCH",
                "conditional inputs require a released FCFF composer",
                status_code=422,
                retryable=False,
            )
        expected = self.prepare_valuation(
            ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=value.valuation_context.data_snapshot_id,
                data_release_manifest_digest=manifest.manifest_digest,
                model_id=value.model_id,
            ),
            policy_id=value.policy_id,
            deadline_at=deadline_at,
        )
        if value.provenance.conditional_revision_ref is not None:
            try:
                expected = self._recompose_revision(
                    value.provenance.conditional_revision_ref,
                    revision_actor=revision_actor,
                    deadline_at=deadline_at,
                    automatic=expected,
                )
            except ConditionalRevisionForbidden as error:
                raise ServiceError(
                    "CONDITIONAL_REVISION_FORBIDDEN",
                    str(error),
                    status_code=403,
                    retryable=False,
                ) from error
            except (ValueError, SnapshotError, DataReleaseError) as error:
                raise ServiceError(
                    "CONDITIONAL_REVISION_INVALID",
                    "retained revision did not reproduce",
                    status_code=422,
                    retryable=False,
                ) from error
        if expected.input is not None:
            resolved, _ = self._resolve_policy(expected.input)
        else:
            resolved = None
        if resolved is None or canonical_bytes(
            resolved.model_dump(exclude={"input_digest"})
        ) != canonical_bytes(value.model_dump(exclude={"input_digest"})):
            raise ServiceError(
                f"{prefix}_INPUT_MISMATCH",
                "conditional calculation requires the exact recomposed release input and joint scenarios",
                status_code=422,
                retryable=False,
            )
        return True

    @timed_valuation_stage("calculation.resolved")
    def _calculate_resolved(
        self,
        resolved: ValuationInputV1,
        resolution: Any,
        *,
        correlation_id: str,
        deadline_at: datetime | None = None,
        revision_actor: RevisionActor | None = None,
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        guard_execution_deadline(deadline_at)
        if resolution.input_digest != resolved.input_digest:
            raise ServiceError(
                "INPUT_DIGEST_MISMATCH",
                "policy resolution is not bound to the calculation input",
                status_code=409,
                retryable=False,
            )
        self._require_released_calculator_model(resolved)
        guard_calculation_budget(resolved, self.config)
        snapshot = self.snapshot(resolved.valuation_context.data_snapshot_id)
        manifest = self._data_release_manifest(
            resolved.valuation_context.data_release_manifest_digest
        )
        if manifest is not None:
            try:
                self._verify_current_release_artifacts(
                    manifest, deadline_at=deadline_at
                )
            except DataReleaseError as error:
                raise ServiceError(
                    error.code, str(error), status_code=422, retryable=False
                ) from error
        self._verify_fact_references(resolved)
        guard_execution_deadline(deadline_at)
        released_conditional = self._is_released_conditional_input(
            resolved, deadline_at=deadline_at, revision_actor=revision_actor
        )
        guard_execution_deadline(deadline_at)
        has_uncertainty = resolved.uncertainty.mode != "none"
        calculation_input = resolved
        calculation_resolution = resolution
        if has_uncertainty:
            try:
                validate_uncertainty_controls(resolved)
            except ValueError as error:
                raise ServiceError(
                    "UNCERTAINTY_INVALID",
                    str(error),
                    status_code=422,
                    retryable=False,
                ) from error
            calculation_input = resolved.model_copy(
                update={
                    "uncertainty": UncertaintyV1(mode="none"),
                    "input_digest": None,
                }
            ).with_digest()
            calculation_resolution = resolution.model_copy(
                update={"input_digest": calculation_input.input_digest}
            )
        try:
            service_owned_uncertainty = (
                released_conditional or is_service_owned_monte_carlo(resolved)
            )
            guard_execution_deadline(deadline_at)
            with valuation_stage("calculation.raw_result"):
                result = calculate(
                    calculation_input,
                    correlation_id=correlation_id,
                    allow_provisional=service_owned_uncertainty,
                )
        except CalculationRefusal as error:
            raise ServiceError(
                error.code,
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        guard_execution_deadline(deadline_at)
        trace = self._trace(calculation_input, result, snapshot, calculation_resolution)
        result = with_calculation_result_hash(
            result.model_copy(
                update={"policy_resolution": calculation_resolution, "trace": trace}
            )
        )
        guard_execution_deadline(deadline_at)
        result = self._persist_evidence(calculation_input, result)
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.quality_status.value}_total")
        if not has_uncertainty:
            return result
        try:
            guard_execution_deadline(deadline_at)
            with valuation_stage("uncertainty.run"):
                uncertainty = run_uncertainty(
                    resolved,
                    base_result=result,
                    allow_provisional=service_owned_uncertainty,
                )
        except (CalculationRefusal, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "uncertainty_invalid"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        if uncertainty.base.result_hash != result.result_hash:
            raise ServiceError(
                "UNCERTAINTY_BASE_MISMATCH",
                "uncertainty did not use the resolved deterministic calculation",
                status_code=422,
                retryable=False,
            )
        uncertainty_request = resolved.model_dump(exclude={"input_digest"})
        guard_execution_deadline(deadline_at)
        uncertainty = self._persist_uncertainty_evidence(
            uncertainty, uncertainty_request
        )
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{uncertainty.status.value}_total")
        if uncertainty.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return uncertainty

    def replay_valuation(self, envelope: ReplayEnvelopeV1) -> ReplayReportV1:
        if (
            envelope.request.provenance.conditional_revision_ref is not None
            or envelope.request.uncertainty.quantile_basis is not None
        ):
            raise ServiceError(
                "CONDITIONAL_REPLAY_UNSUPPORTED",
                "conditional inputs require the authenticated canonical calculation route",
                status_code=422,
                retryable=False,
            )
        if self.artifact_store is None or self.snapshot_repository is None:
            self.metrics.increment("provenance_replay_failures_total")
            raise ServiceError(
                "source_unavailable",
                "replay dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            report = replay_manifest(
                envelope,
                artifact_store=self.artifact_store,
                snapshot_repository=self.snapshot_repository,
            )
        except (ValueError, SnapshotError) as error:
            self.metrics.increment("provenance_replay_failures_total")
            if isinstance(error, SnapshotError):
                raise _snapshot_error(error) from error
            raise ServiceError(
                "replay_mismatch",
                "released evidence did not reproduce",
                status_code=422,
                retryable=False,
            ) from error
        if report.status == "abstain":
            self.metrics.increment("abstention_total")
        return report

    def uncertainty_valuation(
        self, value: UncertaintyRequestV1, *, deadline_at: datetime | None = None
    ) -> UncertaintyReportV1:
        guard_execution_deadline(deadline_at)
        manifest = self._data_release_manifest(
            value.valuation_context.data_release_manifest_digest
        )
        if (
            value.provenance.conditional_revision_ref is not None
            or value.uncertainty.quantile_basis is not None
            or manifest is not None
            and (
                manifest.conditional_capital_policies
                or manifest.conditional_reinvestment_policies
            )
        ):
            raise ServiceError(
                "CONDITIONAL_UNCERTAINTY_ROUTE_UNSUPPORTED",
                "conditional inputs require the canonical calculation route",
                status_code=422,
                retryable=False,
            )
        self._require_released_calculator_model(value)
        if value.policy_id is None:
            raise ServiceError(
                "POLICY_ID_REQUIRED",
                "verified uncertainty calculations require an explicit immutable "
                "policy_id",
                status_code=422,
                retryable=False,
            )
        try:
            validate_uncertainty_controls(
                value.base_input(),
                scenarios=value.scenarios,
                sensitivity=value.sensitivity,
            )
        except ValueError as error:
            raise ServiceError(
                "UNCERTAINTY_INVALID",
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        guard_calculation_budget(value, self.config)
        self.snapshot(value.valuation_context.data_snapshot_id)
        base_value = value.base_input()
        self._verify_fact_references(base_value)
        deterministic_base = base_value.model_copy(
            update={
                "uncertainty": UncertaintyV1(mode="none"),
            }
        ).with_digest()
        resolved, _ = self._resolve_policy(deterministic_base)
        resolved_value = value.model_copy(
            update={
                "policy_id": resolved.policy_id,
                "assumptions": resolved.assumptions,
                "provenance": resolved.provenance,
                "input_digest": None,
            }
        ).with_digest()
        monte_carlo = value.monte_carlo
        if monte_carlo is not None:
            monte_carlo = monte_carlo.model_copy(
                update={"uncertainty": resolved_value.uncertainty}
            )
        try:
            base = self.calculate_valuation(
                resolved,
                correlation_id="uncertainty-base",
                deadline_at=deadline_at,
            )
            if isinstance(base, UncertaintyReportV1):
                base = base.base
            guard_execution_deadline(deadline_at)
            result = run_uncertainty(
                resolved_value,
                monte_carlo=monte_carlo,
                scenarios=value.scenarios,
                sensitivity=value.sensitivity,
                base_result=base,
                input_digest=resolved_value.input_digest,
            )
        except (CalculationRefusal, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "uncertainty_invalid"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        if result.base.result_hash != base.result_hash:
            raise ServiceError(
                "UNCERTAINTY_BASE_MISMATCH",
                "uncertainty did not use the approved deterministic calculation",
                status_code=422,
                retryable=False,
            )
        result = result.model_copy(update={"base": base})
        evidence_request = resolved_value.model_dump(exclude={"input_digest"})
        guard_execution_deadline(deadline_at)
        result = self._persist_uncertainty_evidence(result, evidence_request)
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.status.value}_total")
        if result.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return result


__all__ = ["FundamentalApplication", "UncertaintyRequestV1"]
