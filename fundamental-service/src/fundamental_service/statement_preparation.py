from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from .annual_discovery import AnnualDiscoveryRequestV1
from .annual_discovery_service import AnnualDiscovery
from .application.service import FundamentalApplication
from .automatic_data_release import (
    AutomaticDataReleaseCandidateV1,
    AutomaticDataReleaseService,
)
from .automatic_mapping import automatic_mapping_policy_digest
from .automatic_source_mapping import AutomaticStatementSecIngestionRequestV1
from .contracts import FiscalPeriodSelectorV1, SecFilingSelectorV1
from .data_releases import (
    ArtifactRefV1,
    DataReleaseActivationRequestV1,
    DataReleaseError,
    ReleaseModel,
)
from .dqc_rulesets import DQC_V18_PROFILE_ID
from .issuer_identity import (
    DEFAULT_ORIGINAL_HISTORY_IDENTITY_POLICY,
    DEFAULT_ORIGINAL_SECURITY_POLICY,
)
from .operations import ServiceError, guard_execution_deadline
from .original_preparation import (
    OriginalFilingRuntimeV1,
    OriginalSecuritySelectionV1,
    StatementOriginalPreparationRequestV1,
)
from .registered_statement_rows import registered_statement_namespace
from .serialization import canonical_bytes, sha256_digest
from .source_acquisition import SecAcquisitionUseCase
from .statement_contracts import (
    AnnualStatementsReadRequestV1,
    AnnualStatementsReadResponseV1,
)
from .statement_profiles import annual_statement_profile, statement_executable_digest
from .statement_release_builder import build_statement_release


class AnnualStatementPreparationRequestV1(OriginalSecuritySelectionV1):
    protocol: Literal["annual-statement-preparation-v1"] = (
        "annual-statement-preparation-v1"
    )
    cik: str = Field(pattern=r"^[0-9]{10}$")
    cutoff_at: AwareDatetime
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    original_count: int = Field(default=5, ge=1, le=6)
    mapping_evaluator_id: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)


class AnnualStatementPreparationResultV1(ReleaseModel):
    protocol: Literal["annual-statement-preparation-result-v1"] = (
        "annual-statement-preparation-result-v1"
    )
    annual_discovery: ArtifactRefV1
    original_preparation: ArtifactRefV1
    candidate: ArtifactRefV1
    response: AnnualStatementsReadResponseV1
    activated: bool


def statement_validation_profile_id(
    acquisition: SecAcquisitionUseCase, namespace: str
) -> Literal["sec-efm-us-dqc-v31.0.3", "sec-efm-us-dqc-v18-xule30055-build-v1"]:
    v18 = acquisition.settings.dqc_v18_ruleset_catalog
    modern = acquisition.settings.dqc_ruleset_catalog
    matches = tuple(
        profile
        for profile, catalog in (
            (DQC_V18_PROFILE_ID, v18),
            ("sec-efm-us-dqc-v31.0.3", modern),
        )
        if catalog is not None
        and namespace in {binding.taxonomy_namespace for binding in catalog.bindings}
    )
    if len(matches) != 1:
        raise DataReleaseError(
            "STATEMENT_VALIDATION_NAMESPACE_UNAVAILABLE",
            "the exact original US-GAAP namespace requires one configured validation catalog",
        )
    return (
        "sec-efm-us-dqc-v18-xule30055-build-v1"
        if matches[0] == DQC_V18_PROFILE_ID
        else "sec-efm-us-dqc-v31.0.3"
    )


def prepare_annual_statements(
    request: AnnualStatementPreparationRequestV1,
    *,
    application: FundamentalApplication,
    acquisition: SecAcquisitionUseCase,
    automatic_release: AutomaticDataReleaseService,
    discovery: AnnualDiscovery,
    actor_id: str,
    organization_id: str,
    deadline_at: datetime,
    activate: bool = False,
    expected_revision: int | None = None,
) -> AnnualStatementPreparationResultV1:
    request = AnnualStatementPreparationRequestV1.model_validate_json(
        canonical_bytes(request)
    )
    if (
        organization_id
        not in application.config.release_publish_authorized_organizations
    ):
        raise ServiceError(
            "DATA_RELEASE_FORBIDDEN",
            "the organization is not authorized to publish statement releases",
            status_code=403,
            retryable=False,
        )
    if (
        activate
        and organization_id
        not in application.config.release_activation_authorized_organizations
    ):
        raise ServiceError(
            "DATA_RELEASE_FORBIDDEN",
            "the organization is not authorized to activate statement releases",
            status_code=403,
            retryable=False,
        )
    if organization_id not in acquisition.authorized_organizations:
        raise ServiceError(
            "INGESTION_NOT_AUTHORIZED",
            "organization is not authorized for SEC data acquisition",
            status_code=403,
            retryable=False,
        )
    if (
        application.snapshot_repository is None
        or application.fact_repository is None
        or application.content_store is None
        or application.metadata_store is None
        or application.statement_originals is None
    ):
        raise DataReleaseError(
            "STATEMENT_PREPARATION_UNAVAILABLE",
            "statement preparation requires the service persistence and original owners",
        )
    guard_execution_deadline(deadline_at)
    originals = application.statement_originals
    annual_request = AnnualDiscoveryRequestV1.model_validate(
        dict(
            cik=request.cik,
            valuation_timestamp=request.cutoff_at,
            declared_source_revision=request.source_revision,
            original_count=request.original_count,
            supported_filing_years=acquisition.settings.supported_filing_years,
            supported_filing_forms=acquisition.settings.supported_filing_forms,
        )
    )
    annual, _ = discovery.execute(annual_request, deadline_at=deadline_at)
    if annual.selection.issue_codes or not annual.selection.selected:
        raise DataReleaseError(
            "STATEMENT_ANNUAL_DISCOVERY_UNAVAILABLE",
            "; ".join(annual.selection.issue_codes),
        )
    runtimes = tuple(
        sorted(
            (
                OriginalFilingRuntimeV1(
                    accession_number=filing.accession_number,
                    runtime=acquisition.original_validation_runtime(
                        declared_source_revision=request.source_revision,
                        validation_profile_id=statement_validation_profile_id(
                            acquisition,
                            registered_statement_namespace(
                                request.cik, filing.accession_number
                            ),
                        ),
                    ),
                )
                for filing in annual.selection.selected
            ),
            key=lambda item: item.accession_number,
        )
    )
    preparation = StatementOriginalPreparationRequestV1(
        annual=originals.reference(
            annual.artifact_id, "sec-original-annual-discovery-v1"
        ),
        original_runtimes=runtimes,
        ticker=request.ticker,
        share_class=request.share_class,
        security_selection_policy=request.security_selection_policy
        or DEFAULT_ORIGINAL_SECURITY_POLICY,
        history_identity_policy=request.history_identity_policy
        or DEFAULT_ORIGINAL_HISTORY_IDENTITY_POLICY,
    )
    prepared, _ = originals.execute(preparation, deadline_at=deadline_at)
    original_ref = originals.reference(
        prepared.artifact_id, "sec-original-preparation-v1"
    )
    profile = annual_statement_profile(executable_digest=statement_executable_digest())
    ingestions = []
    for item in prepared.filings:
        guard_execution_deadline(deadline_at)
        if item.issue_codes or item.identity is None:
            continue
        validation = originals.read_validation(item.validation.artifact_id)
        runtime, filing = validation.request.runtime, validation.request.filing
        ingestion = AutomaticStatementSecIngestionRequestV1(
            contract_version="fundamental.v1",
            identity=item.identity,
            cik=request.cik,
            ticker=item.identity.security_id,
            identity_basis="original-filing-dei-v1",
            valuation_timestamp=request.cutoff_at,
            required_fields=tuple(row.row_id for row in profile.rows),
            source_selection_policy="sec-pit-v1",
            coverage_profile=profile.profile_id,
            legal_use_profile="sec-public-us-v1",
            filing=SecFilingSelectorV1(
                accession_number=filing.accession_number,
                forms=("10-K",),
                lookback_days=3650,
            ),
            fiscal_period_selector=FiscalPeriodSelectorV1(
                mode="latest_complete", count=1
            ),
            parser_version=runtime.arelle_version,
            validation_profile_id=runtime.validation_profile_id,
            taxonomy_manifest_id=runtime.taxonomy_manifest_id,
            taxonomy_version=runtime.taxonomy_version,
            policy_version="annual-statements-v1",
            source_revision=request.source_revision,
            evaluator_id=request.mapping_evaluator_id,
            mapping_policy_digest=automatic_mapping_policy_digest(),
            mapping_version=request.mapping_version,
            statement_profile=profile,
            original_preparation=original_ref,
        )
        ingestions.append(
            acquisition.execute(
                ingestion,
                caller_principal=actor_id,
                organization_id=organization_id,
                correlation_id="annual-statements:" + sha256_digest(request),
                deadline_at=deadline_at,
            )
        )
    release = build_statement_release(
        original_ref,
        tuple(ingestions),
        originals=originals,
        snapshots=application.snapshot_repository,
        facts=application.fact_repository,
        mappings=application.metadata_store,
        artifacts=application.artifact_store,
        source_revision=request.source_revision,
        mapping_version=request.mapping_version,
    )
    receipt = automatic_release.verify_and_sign(release, deadline_at=deadline_at)
    if receipt.candidate_publication is None or receipt.decision.status != "passed":
        raise DataReleaseError(
            "STATEMENT_RELEASE_BLOCKED", "; ".join(receipt.decision.issue_codes)
        )
    candidate = AutomaticDataReleaseCandidateV1.model_validate_json(
        application.artifact_store.read(
            receipt.candidate_publication.artifact.artifact_id
        )
    )
    guard_execution_deadline(deadline_at)
    application.publish_data_release_candidate(
        candidate.manifest, candidate.verification
    )
    if activate:
        active = application.metadata_store.get_active_data_release(
            candidate.manifest.profile_id
        )
        if (
            active is None
            or active.manifest_digest != candidate.manifest.manifest_digest
        ):
            revision = 0 if active is None else active.revision
            if expected_revision is not None and revision != expected_revision:
                raise DataReleaseError(
                    "DATA_RELEASE_POINTER_CONFLICT",
                    "the active statement release revision differs from the operator expectation",
                )
            application.change_active_data_release(
                candidate.manifest.profile_id,
                DataReleaseActivationRequestV1(
                    manifest_digest=candidate.manifest.manifest_digest,
                    expected_revision=revision,
                    expected_manifest_digest=None
                    if active is None
                    else active.manifest_digest,
                    operation="activate",
                    command_id=sha256_digest(
                        {
                            "operation": "annual-statement-activation-v1",
                            "request": request,
                            "manifest_digest": candidate.manifest.manifest_digest,
                            "expected_revision": revision,
                        }
                    ),
                    reason="validated annual statement candidate",
                ),
                actor_id=actor_id,
                organization_id=organization_id,
                correlation_id="annual-statements:" + sha256_digest(request),
            )
    response = application.read_annual_statements(
        AnnualStatementsReadRequestV1(
            contract_version="fundamental.annual-statements.v1",
            data_release_manifest_digest=candidate.manifest.manifest_digest,
            cutoff_at=request.cutoff_at,
        ),
        deadline_at=deadline_at,
    )
    record = receipt.candidate_publication.artifact
    return AnnualStatementPreparationResultV1(
        annual_discovery=prepared.request.annual,
        original_preparation=original_ref,
        candidate=ArtifactRefV1(
            artifact_id=record.artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role="automatic-release-candidate-v1",
        ),
        response=response,
        activated=activate,
    )
