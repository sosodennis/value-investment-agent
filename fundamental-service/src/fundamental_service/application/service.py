"""Typed application use cases assembled by the HTTP composition root."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from typing import Any, overload

from pydantic import model_validator

from ..calculator import (
    CalculationRefusal,
    calculate,
    validate,
    with_calculation_result_hash,
)
from ..contracts import (
    ArtifactReferenceV1,
    CalculationArtifactV1,
    CalculationEvidenceV1,
    CalculationTraceV1,
    FactsReadRequestV1,
    FactsReadResponseV1,
    FiscalPeriodSelectorV1,
    PolicyValuationInputV1,
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
    DataReleaseActivationCommandV1,
    DataReleaseActivationRequestV1,
    DataReleaseCandidateReceiptV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseVerificationV1,
    ReleaseResolutionCacheKeyV1,
)
from ..facts import (
    CanonicalFactRepository,
    canonical_fact_digest,
    verify_accounting_role_evidence,
)
from ..equity_award_evidence import load_release_dilution_evidence
from ..equity_dilution import DilutionError
from ..quote_providers import QuoteSourceProviderPort
from ..macro_series import MacroSeriesProviderPort
from ..market_reference import MarketReferenceProviderPort
from ..source_admission import SourceAdmissionV1, SourceUsePolicyV1
from ..source_admission_evidence import load_release_source_admissions
from ..market_source_selection import MarketSourceError, verify_observed_market_inputs
from ..market_reference_evidence import load_release_market_reference_selection
from ..market_reference_selection import IssuerMarketReferenceSelectionV1
from ..fiscal_periods import resolve_fiscal_periods
from ..governance import ModelInventory
from ..history_composition import verify_history_components
from ..operations import (
    OperationalMetrics,
    OperationsConfig,
    ServiceError,
    guard_calculation_budget,
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
from ..serialization import is_digest, sha256_digest
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
    ApprovedMarketPolicyInputsV1,
    AutomaticValuationPreparationV1,
    ManualValuationOverrideRequestV1,
    apply_manual_override,
    prepare_automatic_valuation,
)
from ..valuation_requirements import (
    select_released_facts,
    valuation_requirements_profile,
)


class UncertaintyRequestV1(ValuationInputV1):
    """Valuation input with caller-owned uncertainty controls."""

    scenarios: tuple[ScenarioV1, ...] = ()
    sensitivity: tuple[SensitivityRequestV1, ...] = ()
    monte_carlo: MonteCarloRequestV1 | None = None

    @model_validator(mode="after")
    def digest_and_approval(self) -> UncertaintyRequestV1:
        payload = self.model_dump(
            exclude={
                "input_digest",
                "caller_approval",
            }
        )
        computed = sha256_digest(payload)
        if self.input_digest is not None and (
            not is_digest(self.input_digest) or self.input_digest != computed
        ):
            raise ValueError("input_digest does not match complete uncertainty request")
        if (
            self.caller_approval is not None
            and self.caller_approval.input_digest != computed
        ):
            raise ValueError("caller approval is bound to a different input_digest")
        return self

    def base_input(self) -> ValuationInputV1:
        payload = self.model_dump(exclude={"scenarios", "sensitivity", "monte_carlo"})
        payload["input_digest"] = None
        payload["caller_approval"] = None
        return ValuationInputV1.model_validate(payload)

    def with_digest(self) -> UncertaintyRequestV1:
        payload = self.model_dump(exclude={"input_digest", "caller_approval"})
        return self.model_copy(update={"input_digest": sha256_digest(payload)})


def _approved_market_policy(
    policy: PolicyRecordV1 | None,
    *,
    valuation_timestamp: datetime | None = None,
    currency: str | None = None,
    source_admissions: tuple[SourceAdmissionV1, ...] = (),
    reference_selection: IssuerMarketReferenceSelectionV1 | None = None,
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
        "CALLER_APPROVAL_CONFLICT",
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
        if manifest.manifest_digest != manifest_digest:
            raise ServiceError(
                "DATA_RELEASE_MANIFEST_MISMATCH",
                "the stored data release does not match the requested digest",
                status_code=409,
                retryable=False,
            )
        return manifest

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

    def active_data_release(self, profile_id: str) -> ActiveDataReleaseWithManifestV1:
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
        return active

    def change_active_data_release(
        self,
        profile_id: str,
        request: DataReleaseActivationRequestV1,
        *,
        actor_id: str,
        organization_id: str,
        correlation_id: str,
    ) -> ActiveDataReleaseWithManifestV1:
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
            active = self.metadata_store.compare_and_swap_data_release(command)
            manifest = self.metadata_store.get_data_release_manifest(
                active.manifest_digest
            )
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
        return ActiveDataReleaseWithManifestV1(active=active, manifest=manifest)

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
        evidence_request = request.model_copy(update={"caller_approval": None})
        evidence = CalculationEvidenceV1(
            contract_version="fundamental.v1",
            request=evidence_request,
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

    def read_facts(self, request: FactsReadRequestV1) -> FactsReadResponseV1:
        if self.fact_repository is None:
            raise ServiceError(
                "source_unavailable",
                "canonical fact dependencies are unavailable",
                status_code=503,
                retryable=True,
            )
        snapshot = self.snapshot(request.snapshot_id)
        try:
            facts = self.fact_repository.resolve(
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                required_fields=request.required_fields,
            )
        except SnapshotError as error:
            raise _snapshot_error(error) from error
        release_manifest = self._data_release_manifest(
            request.data_release_manifest_digest
        )
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
        profile = valuation_requirements_profile(request.model_id)
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
        declared_digests = {
            reference.fact_id: reference.fact_digest
            for reference in declared_snapshot.facts
        }
        try:
            for fact_id, expected_digest in declared_digests.items():
                fact = self.fact_repository.get(fact_id)
                if canonical_fact_digest(fact) != expected_digest:
                    raise ServiceError(
                        "DATA_RELEASE_FACT_MISMATCH",
                        "a canonical fact does not match the pinned data release",
                        status_code=409,
                        retryable=False,
                    )
                facts.append(fact)
        except ServiceError:
            raise
        except SnapshotError as error:
            raise ServiceError(
                "FACT_NOT_FOUND",
                "a release-declared canonical fact is unavailable",
                status_code=404,
                retryable=False,
            ) from error

        selection = select_released_facts(
            facts,
            profile=profile,
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
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
        mapping_reader = getattr(self.metadata_store, "get_mapping", None)
        if callable(mapping_reader):
            assert manifest is not None
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
        elif self.require_metadata:
            raise ServiceError(
                "DATA_RELEASE_MAPPING_UNAVAILABLE",
                "release mapping metadata is unavailable",
                status_code=503,
                retryable=True,
            )
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

    def prepare_valuation(
        self, request: ValuationEvidenceReadRequestV1
    ) -> AutomaticValuationPreparationV1:
        """Prepare one valuation from the pinned release and service policy."""

        evidence = self.read_valuation_evidence(request)
        snapshot = self.snapshot(request.snapshot_id)
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
        model_version = f"{request.model_id}-v2"
        policy = None
        if self.policy_registry is not None:
            try:
                policy = self.policy_registry.select_policy(
                    model_id=request.model_id,
                    model_version=model_version,
                    valuation_timestamp=snapshot.valuation_timestamp,
                    policy_id=None,
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
            reference_selection = load_release_market_reference_selection(
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
            )
        except (MarketSourceError, DataReleaseError, SnapshotError) as error:
            raise ServiceError(
                error.code, str(error), status_code=422, retryable=False
            ) from error
        try:
            dilution = load_release_dilution_evidence(
                self._data_release_manifest(request.data_release_manifest_digest),
                snapshot=snapshot,
                artifacts=self.artifact_store,
                released_facts=evidence.facts,
                quote_providers=self.quote_providers,
            )
        except (DilutionError, SnapshotError, ValueError) as error:
            raise ServiceError(
                getattr(error, "code", "DILUTION_EVIDENCE_INVALID"),
                str(error),
                status_code=422,
                retryable=False,
            ) from error
        return prepare_automatic_valuation(
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
        )

    def apply_manual_override(
        self, request: ManualValuationOverrideRequestV1
    ) -> AutomaticValuationPreparationV1:
        try:
            return apply_manual_override(
                request.preparation,
                path=request.path,
                value=request.value,
                provenance=request.provenance,
            )
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
                self.snapshot(cached_resolution.snapshot_id)
                self.metrics.increment("cache_hit_total")
                return cached_resolution
            if cache_status == "hit":
                self.release_cache.invalidate(cache_key)
                cache_status = "stale"
            if cache_status == "stale":
                self.metrics.increment("cache_stale_total")
            else:
                self.metrics.increment("cache_miss_total")

        candidates = self.snapshot_repository.find(
            identity=request.identity,
            valuation_timestamp=request.valuation_timestamp,
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
            declared_snapshot = (
                None
                if declared_snapshots is None
                else declared_snapshots[snapshot.snapshot_id]
            )
            if (
                declared_snapshot is not None
                and snapshot.manifest_digest != declared_snapshot.manifest_digest
            ):
                raise ServiceError(
                    "DATA_RELEASE_SNAPSHOT_MISMATCH",
                    "a release snapshot does not match its declared manifest",
                    status_code=409,
                    retryable=False,
                )
            try:
                facts = self.fact_repository.resolve(
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
                list_facts = getattr(self.fact_repository, "list", None)
                if not callable(list_facts):
                    raise ServiceError(
                        "FISCAL_PERIODS_UNAVAILABLE",
                        "the fact repository cannot resolve issuer fiscal periods",
                        status_code=503,
                        retryable=True,
                    )
                selection = resolve_fiscal_periods(
                    list_facts(),
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
            if declared_snapshot is not None:
                assert active_release is not None
                self._verify_release_snapshot_and_facts(
                    active_release.manifest,
                    snapshot,
                    facts,
                    required_fields=request.required_fields,
                )
            result = SnapshotResolutionV1(
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

    def artifact(self, artifact_id: str) -> ArtifactRecordV1:
        if self.artifact_store is None:
            raise ServiceError(
                "source_unavailable",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
        try:
            return self.artifact_store.get(artifact_id)
        except SnapshotError as error:
            raise _snapshot_error(error) from error

    def artifact_content(self, artifact_id: str) -> tuple[ArtifactRecordV1, bytes]:
        record = self.artifact(artifact_id)
        if self.artifact_store is None:  # pragma: no cover - guarded by artifact()
            raise ServiceError(
                "source_unavailable",
                "released artifact is unavailable",
                status_code=503,
                retryable=True,
            )
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
        self, value: ValuationInputV1, *, correlation_id: str
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
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
            resolved, resolution, correlation_id=correlation_id
        )

    def calculate_with_policy(
        self, value: PolicyValuationInputV1, *, correlation_id: str
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
        resolved, resolution = self._resolve_policy_overrides(value)
        return self._calculate_resolved(
            resolved, resolution, correlation_id=correlation_id
        )

    def _calculate_resolved(
        self,
        resolved: ValuationInputV1,
        resolution: Any,
        *,
        correlation_id: str,
    ) -> CalculationArtifactV1 | UncertaintyReportV1:
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
        self._verify_fact_references(resolved)
        has_uncertainty = resolved.uncertainty.mode != "none"
        calculation_input = resolved
        calculation_resolution = resolution
        if has_uncertainty:
            if (
                resolved.caller_approval is not None
                and resolved.caller_approval.decision != "approved"
            ):
                raise ServiceError(
                    "CALLER_APPROVAL_REJECTED",
                    "caller rejected this exact valuation input",
                    status_code=422,
                    retryable=False,
                )
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
                    "caller_approval": None,
                }
            ).with_digest()
            calculation_resolution = resolution.model_copy(
                update={"input_digest": calculation_input.input_digest}
            )
        try:
            service_owned_uncertainty = is_service_owned_monte_carlo(resolved)
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
        trace = self._trace(calculation_input, result, snapshot, calculation_resolution)
        result = with_calculation_result_hash(
            result.model_copy(
                update={"policy_resolution": calculation_resolution, "trace": trace}
            )
        )
        result = self._persist_evidence(calculation_input, result)
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.quality_status.value}_total")
        if not has_uncertainty:
            return result
        try:
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
        uncertainty_request = resolved.model_dump(
            exclude={"input_digest", "caller_approval"}
        )
        uncertainty = self._persist_uncertainty_evidence(
            uncertainty, uncertainty_request
        )
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{uncertainty.status.value}_total")
        if uncertainty.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return uncertainty

    def replay_valuation(self, envelope: ReplayEnvelopeV1) -> ReplayReportV1:
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

    def uncertainty_valuation(self, value: UncertaintyRequestV1) -> UncertaintyReportV1:
        self._require_released_calculator_model(value)
        if value.policy_id is None:
            raise ServiceError(
                "POLICY_ID_REQUIRED",
                "verified uncertainty calculations require an explicit immutable "
                "policy_id",
                status_code=422,
                retryable=False,
            )
        if (
            value.caller_approval is not None
            and value.caller_approval.decision != "approved"
        ):
            raise ServiceError(
                "CALLER_APPROVAL_REJECTED",
                "caller rejected this exact valuation input",
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
                "caller_approval": None,
            }
        ).with_digest()
        resolved, _ = self._resolve_policy(deterministic_base)
        resolved_value = value.model_copy(
            update={
                "policy_id": resolved.policy_id,
                "assumptions": resolved.assumptions,
                "provenance": resolved.provenance,
                "input_digest": None,
                "caller_approval": None,
            }
        ).with_digest()
        if (
            value.caller_approval is not None
            and value.caller_approval.input_digest != resolved_value.input_digest
        ):
            raise ServiceError(
                "CALLER_APPROVAL_CONFLICT",
                "caller approval is bound to a different resolved input_digest",
                status_code=409,
                retryable=False,
            )
        if value.caller_approval is not None:
            resolved_value = resolved_value.model_copy(
                update={"caller_approval": value.caller_approval}
            )
        monte_carlo = value.monte_carlo
        if monte_carlo is not None:
            monte_carlo = monte_carlo.model_copy(
                update={"uncertainty": resolved_value.uncertainty}
            )
        try:
            base = self.calculate_valuation(
                resolved,
                correlation_id="uncertainty-base",
            )
            if isinstance(base, UncertaintyReportV1):
                base = base.base
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
        evidence_request = resolved_value.model_dump(
            exclude={"input_digest", "caller_approval"}
        )
        result = self._persist_uncertainty_evidence(result, evidence_request)
        self.metrics.increment("quality_status_total")
        self.metrics.increment(f"quality_status_{result.status.value}_total")
        if result.status.value in {"abstain", "degraded"}:
            self.metrics.increment("abstention_total")
        return result


__all__ = ["FundamentalApplication", "UncertaintyRequestV1"]
