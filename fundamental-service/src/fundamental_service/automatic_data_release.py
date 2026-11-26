"""Deployment-owned verification and deterministic trusted release signing."""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field, TypeAdapter, model_validator, field_validator

from .automatic_release_evidence import require_automatic_release_sources
from .publication_codec import decode_release_manifest

from .parser_action_evidence import require_current_parser_action_refs
from .parser_action_identity import ParserBuildChecks
from .automatic_market_authority import (
    AutomaticMarketAuthorityRuntime,
    AutomaticMarketPolicyAuthorizationV1,
    authorize_compiled_market_policy,
)
from .command_artifacts import EvidenceArtifactStore
from .contracts import InitialModelId
from .contracts import SourceSnapshotV1
from .data_releases import (
    REQUIRED_DATA_RELEASE_GATES,
    ArtifactRefV1,
    DataReleaseContentRequestV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    IssuerOperatingReleaseManifestV1,
    ReleaseModel,
    sign_data_release_verification,
)
from .facts import CanonicalFactRepository, CanonicalMappingV1
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort
from .market_reference_evidence import read_release_market_reference_plan
from .terminal_growth_evidence import read_release_terminal_growth_plan
from .policies import (
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    executable_model_specs,
)
from .operations import guard_execution_deadline
from .quote_providers import QuoteSourceProviderPort
from .release_runner import (
    DataReleaseCanaryRunner,
    ReleaseMappingReader,
    ReleaseSnapshotReader,
)
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .source_admission import SourceUsePolicyV1
from .source_admission_evidence import load_release_source_admissions
from .source_plan_contracts import AutomaticSourcePreparationPlanV1
from .statement_contracts import StatementProfileV1
from .statement_profiles import annual_statement_profile, statement_executable_digest
from .statement_releases import read_statement_release
from .original_preparation import OriginalPreparation
from .snapshots import ContentAddressedStore
from .valuation_release_inputs import valuation_release_requirements
from .valuation_requirements import (
    composite_working_capital_requirements_profile,
    operating_forecast_requirements_profile,
)


def automatic_release_suite_digest() -> str:
    """A deployment trust root pins the executable suite, including its owners."""
    root = Path(__file__).parent
    return sha256_digest(
        {
            "protocol": "automatic-data-release-suite-v1",
            "runtime": {
                "python": sys.version,
                **{
                    package: version(package)
                    for package in ("arelle-release", "cryptography", "pydantic")
                },
            },
            "sources": {
                path.relative_to(root).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(root.rglob("*.py"))
            },
        }
    )


class AutomaticDataReleasePolicyV1(ReleaseModel):
    protocol: Literal["automatic-data-release-policy-v1"] = (
        "automatic-data-release-policy-v1"
    )
    profile_id: str = Field(min_length=1)
    scope: Literal["security", "issuer-operating"]
    model_id: InitialModelId
    model_version: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    requirements_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1)
    quality_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verifier_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)
    market_policy_authorization: AutomaticMarketPolicyAuthorizationV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class AutomaticStatementReleasePolicyV1(ReleaseModel):
    protocol: Literal["automatic-statement-release-policy-v1"] = (
        "automatic-statement-release-policy-v1"
    )
    scope: Literal["annual-statements"] = "annual-statements"
    statement_profile: StatementProfileV1
    mapping_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    validation_profile_digests: tuple[str, ...] = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)

    @model_validator(mode="after")
    def statement_policy_is_installed(self) -> AutomaticStatementReleasePolicyV1:
        if self.statement_profile != annual_statement_profile(
            executable_digest=statement_executable_digest()
        ) or self.validation_profile_digests != tuple(
            sorted(set(self.validation_profile_digests))
        ):
            raise ValueError(
                "statement release policy requires the installed profile and distinct validation pins"
            )
        return self


_AUTOMATIC_RELEASE_POLICY = TypeAdapter(
    AutomaticDataReleasePolicyV1 | AutomaticStatementReleasePolicyV1
)


class AutomaticDataReleaseRequestV1(ReleaseModel):
    manifest: IssuerOperatingReleaseManifestV1 | DataReleaseManifestV1
    content: DataReleaseContentRequestV1
    source_plan: AutomaticSourcePreparationPlanV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("manifest", mode="before")
    @classmethod
    def exact_purpose(cls, value: object) -> DataReleaseManifestV1:
        manifest = decode_release_manifest(canonical_bytes(value))
        if not isinstance(manifest, DataReleaseManifestV1):
            raise ValueError("fiscal releases require the refs-only fiscal workflow")
        return manifest


class AutomaticDataReleaseCandidateV1(ReleaseModel):
    manifest: IssuerOperatingReleaseManifestV1 | DataReleaseManifestV1
    verification: DataReleaseVerificationV1

    @field_validator("manifest", mode="before")
    @classmethod
    def exact_purpose(cls, value: object) -> DataReleaseManifestV1:
        manifest = decode_release_manifest(canonical_bytes(value))
        if not isinstance(manifest, DataReleaseManifestV1):
            raise ValueError("fiscal releases require the refs-only fiscal workflow")
        return manifest


class AutomaticDataReleaseDecisionV1(ReleaseModel):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["passed", "blocked"]
    issue_codes: tuple[str, ...] = ()
    content_report_digest: str | None = None
    regulatory_evidence_digests: tuple[str, ...] = ()
    market_policy_digests: tuple[str, ...] = ()


class AutomaticDataReleaseReceiptV1(ReleaseModel):
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: AutomaticDataReleaseDecisionV1
    input_publication: ArtifactPublicationV1
    decision_publication: ArtifactPublicationV1
    candidate_publication: ArtifactPublicationV1 | None
    canary_publication: ArtifactPublicationV1 | None
    wrote: bool


class AutomaticDataReleaseService:
    """Sign checked immutable candidates; never activate or approve a valuation."""

    def __init__(
        self,
        *,
        snapshots: ReleaseSnapshotReader,
        facts: CanonicalFactRepository,
        mappings: ReleaseMappingReader,
        artifacts: EvidenceArtifactStore,
        trust_roots: DataReleaseTrustRootsV1,
        policy: AutomaticDataReleasePolicyV1 | AutomaticStatementReleasePolicyV1,
        private_key: Ed25519PrivateKey,
        source_revision: str,
        quote_providers: tuple[QuoteSourceProviderPort, ...] = (),
        macro_providers: tuple[MacroSeriesProviderPort, ...] = (),
        reference_providers: tuple[MarketReferenceProviderPort, ...] = (),
        source_use_policy: SourceUsePolicyV1 | None = None,
        policy_registry: PolicyRegistry | None = None,
        market_authority: AutomaticMarketAuthorityRuntime | None = None,
        statement_originals: OriginalPreparation | None = None,
        statement_content: ContentAddressedStore | None = None,
    ) -> None:
        self._snapshots, self._mappings, self._artifacts = (
            snapshots,
            mappings,
            artifacts,
        )
        self._roots = DataReleaseTrustRootsV1.model_validate_json(
            canonical_bytes(trust_roots)
        )
        self._policy = _AUTOMATIC_RELEASE_POLICY.validate_json(canonical_bytes(policy))
        self._key = private_key
        self._revision = source_revision
        self._source_use_policy = source_use_policy
        self._policy_registry = policy_registry
        self._market_authority = market_authority
        self._macro_providers = macro_providers
        self._reference_providers = reference_providers
        self._canary = partial(
            DataReleaseCanaryRunner,
            snapshot_repository=snapshots,
            fact_repository=facts,
            mapping_reader=mappings,
            artifact_reader=artifacts,
            trust_roots=self._roots,
            quote_providers=quote_providers,
            macro_providers=macro_providers,
            reference_providers=reference_providers,
            source_use_policy=source_use_policy,
            statement_originals=statement_originals,
            statement_content=statement_content,
        )

    def _market_registry(
        self, request: AutomaticDataReleaseRequestV1
    ) -> tuple[PolicyRegistry | None, tuple[PolicyRecordV1, ...]]:
        if isinstance(self._policy, AutomaticStatementReleasePolicyV1):
            return None, ()
        authorization = self._policy.market_policy_authorization
        if authorization is None:
            return self._policy_registry, ()
        if (
            self._policy.scope != "security"
            or self._policy_registry is None
            or self._market_authority is None
            or self._source_use_policy is None
            or request.source_plan is None
        ):
            raise DataReleaseError(
                "AUTOMATIC_MARKET_AUTHORITY_UNAVAILABLE",
                "automatic market authority requires configured deployment owners",
            )
        model = self._policy_registry.model(
            self._policy.model_id, self._policy.model_version
        )
        if model is None:
            raise DataReleaseError("MODEL_UNSUPPORTED", "deployment model unavailable")
        admissions = load_release_source_admissions(
            request.manifest,
            artifacts=self._artifacts,
            policy=self._source_use_policy,
            macro_providers=self._macro_providers,
            reference_providers=self._reference_providers,
        )
        policies = []
        for ref in request.manifest.snapshot_refs:
            snapshot = self._snapshots.get(ref.snapshot_id)
            if not isinstance(snapshot, SourceSnapshotV1):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_POLICY_MISMATCH",
                    "automatic market authority requires a security snapshot",
                )
            policy = authorize_compiled_market_policy(
                request.manifest,
                authorization=authorization,
                model=model,
                snapshot=snapshot,
                admissions=admissions,
                artifacts=self._artifacts,
                owners=self._market_authority,
                source_plan=request.source_plan,
                source_revision=self._revision,
            )
            existing = self._policy_registry.policy(policy.policy_id)
            if existing is not None and existing != policy:
                raise DataReleaseError("POLICY_IMMUTABLE", "policy identity conflict")
            policies.append(policy)
        staged = PolicyRegistry(
            self._policy_registry.models(),
            (
                *tuple(
                    item
                    for item in self._policy_registry.policies()
                    if item.policy_id not in {policy.policy_id for policy in policies}
                ),
                *policies,
            ),
        )
        return staged, tuple(policies)

    def _require_policy(self, request: AutomaticDataReleaseRequestV1) -> None:
        policy, manifest = self._policy, request.manifest
        verifier = self._roots.verifiers.get(policy.verifier_id)
        if (
            verifier is None
            or verifier.workflow_identity != policy.workflow_identity
            or verifier.verification_suite_digest != automatic_release_suite_digest()
            or verifier.public_key() != self._key.public_key().public_bytes_raw()
        ):
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_AUTHORITY_MISMATCH",
                "machine release requires its own trusted key, workflow and executable suite",
            )
        if request.content.source_revision != self._revision:
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_REVISION_MISMATCH",
                "request revision must match the installed deployment",
            )
        statement = read_statement_release(manifest, artifacts=self._artifacts)
        if isinstance(policy, AutomaticStatementReleasePolicyV1):
            if (
                statement is None
                or request.source_plan is not None
                or statement.projection.profile != policy.statement_profile
                or statement.mapping_version != policy.mapping_version
                or manifest.parser_version != policy.parser_version
                or any(
                    not isinstance(
                        snapshot := self._snapshots.get(ref.snapshot_id),
                        SourceSnapshotV1,
                    )
                    or snapshot.validation_profile_digest is None
                    or snapshot.validation_profile_digest
                    not in policy.validation_profile_digests
                    for ref in manifest.snapshot_refs
                )
                or any(
                    self._read_mapping(ref.mapping_id).mapping_version
                    != policy.mapping_version
                    for ref in manifest.mapping_refs
                )
            ):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_POLICY_MISMATCH",
                    "statement release must match its installed row, source, and validation policy",
                )
            return
        if statement is not None:
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_POLICY_MISMATCH",
                "statement releases require their explicit deployment signing policy",
            )
        issuer_scope = isinstance(manifest, IssuerOperatingReleaseManifestV1)
        if isinstance(manifest, IssuerOperatingReleaseManifestV1):
            profile = (
                composite_working_capital_requirements_profile(policy.model_id)
                if manifest.working_capital_inputs
                else operating_forecast_requirements_profile(policy.model_id)
            )
            version: str | None = manifest.model_version
            if manifest.model_id != policy.model_id:
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_POLICY_MISMATCH",
                    "issuer model must match deployment policy",
                )
        else:
            profile = valuation_release_requirements(manifest, policy.model_id)
            versions = {
                item.model_version for item in manifest.conditional_capital_policies
            }
            versions.update(
                item.recipe.model_version
                for item in manifest.conditional_reinvestment_policies
            )
            working = manifest.valuation_working_capital_policy
            if working is not None:
                versions.add(working.model_version)
            version = next(iter(versions)) if len(versions) == 1 else None
        if (
            issuer_scope != (policy.scope == "issuer-operating")
            or manifest.profile_id != policy.profile_id
            or profile.digest != policy.requirements_profile_digest
            or manifest.required_fields != profile.required_fact_fields
            or version != policy.model_version
            or not any(
                (model.model_id, model.model_version)
                == (policy.model_id, policy.model_version)
                for model in executable_model_specs()
            )
            or manifest.parser_version != policy.parser_version
            or manifest.quality_profile_digest != policy.quality_profile_digest
            or any(
                self._read_mapping(ref.mapping_id).mapping_version
                != policy.mapping_version
                for ref in manifest.mapping_refs
            )
        ):
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_POLICY_MISMATCH",
                "release must match the complete installed model, source and field profile",
            )

    def _read_mapping(self, mapping_id: str) -> CanonicalMappingV1:
        try:
            return self._mappings.get_mapping(mapping_id)
        except Exception as error:
            raise DataReleaseError(
                "DATA_RELEASE_MAPPING_UNAVAILABLE",
                "release mapping is unavailable from its configured repository",
            ) from error

    def _require_market_model(
        self,
        manifest: DataReleaseManifestV1,
        *,
        registry: PolicyRegistry | None = None,
    ) -> tuple[str, ...]:
        if self._policy.scope != "security":
            return ()
        plans = (
            read_release_market_reference_plan(manifest, artifacts=self._artifacts),
            read_release_terminal_growth_plan(manifest, artifacts=self._artifacts),
        )
        registry = registry or self._policy_registry
        if registry is None or any(plan is None for plan in plans):
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_MARKET_POLICY_MISSING",
                "machine security releases require both deployed market selection plans",
            )
        policy_ids = {plan.policy_id for plan in plans if plan is not None}
        checked = []
        for ref in manifest.snapshot_refs:
            snapshot = self._snapshots.get(ref.snapshot_id)
            if not isinstance(snapshot, SourceSnapshotV1):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_POLICY_MISMATCH",
                    "market policy requires a security snapshot",
                )
            try:
                effective = registry.select_policy(
                    model_id=self._policy.model_id,
                    model_version=self._policy.model_version,
                    valuation_timestamp=snapshot.valuation_timestamp,
                    policy_id=None,
                    issuer_id=snapshot.identity.issuer_id,
                    data_release_manifest_digest=manifest.manifest_digest,
                )
            except PolicyError as error:
                raise DataReleaseError(error.code, str(error)) from error
            if policy_ids != {effective.policy_id}:
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_MARKET_MODEL_MISMATCH",
                    "release market plans must select the formal composer's exact effective model policy",
                )
            checked.append(effective.policy_digest)
        return tuple(sorted(checked))

    def verify_and_sign(
        self,
        request: AutomaticDataReleaseRequestV1,
        *,
        deadline_at: datetime | None = None,
    ) -> AutomaticDataReleaseReceiptV1:
        guard_execution_deadline(deadline_at)
        build_checks = ParserBuildChecks()
        request = AutomaticDataReleaseRequestV1.model_validate_json(
            canonical_bytes(request)
        )
        preparation_error = None
        registry = self._policy_registry
        staged_policies: tuple[PolicyRecordV1, ...] = ()
        try:
            self._require_policy(request)
            registry, staged_policies = self._market_registry(request)
        except (DataReleaseError, SnapshotError, ValueError) as error:
            preparation_error = error
        payload = {
            "policy": self._policy,
            "request": request,
            "deployment": {
                "source_revision": self._revision,
                "suite_digest": automatic_release_suite_digest(),
                "trust_roots_digest": sha256_digest(self._roots),
                "signing_public_key": self._key.public_key().public_bytes_raw().hex(),
                "source_use_policy_digest": sha256_digest(self._source_use_policy),
                "market_registry_digest": sha256_digest(
                    {
                        "policies": tuple(
                            item
                            for item in sorted(
                                self._policy_registry.policies(),
                                key=lambda item: item.policy_id,
                            )
                            if item not in staged_policies
                        ),
                        "models": tuple(
                            sorted(
                                self._policy_registry.models(),
                                key=lambda item: (item.model_id, item.model_version),
                            )
                        ),
                    }
                    if self._policy_registry is not None
                    else None
                ),
            },
        }
        input_digest = sha256_digest(payload)
        guard_execution_deadline(deadline_at)
        input_pub = self._artifacts.put_with_receipt(
            "automatic-release-input-" + input_digest,
            payload,
            dependency_hashes=(
                request.manifest.manifest_digest,
                sha256_digest(self._policy),
            ),
        )
        publications = [input_pub]
        candidate_pub = canary_pub = None
        try:
            if preparation_error is not None:
                raise preparation_error
            runner = self._canary(policy_registry=registry)
            content = runner.validate_content(request.manifest, request.content)
            market_policies = self._require_market_model(
                request.manifest, registry=registry
            )
            if self._policy.scope == "security" and len(
                content.market_policy_checks
            ) != len(request.manifest.snapshot_refs):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_MARKET_POLICY_MISSING",
                    "security signing requires a checked deployment market policy for every snapshot",
                )
            if isinstance(self._policy, AutomaticStatementReleasePolicyV1):
                regulatory = content.checked_regulatory_evidence_digests
                if not regulatory:
                    raise DataReleaseError(
                        "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING",
                        "statement signing requires independently validated source evidence",
                    )
            else:
                regulatory = require_automatic_release_sources(
                    request.manifest,
                    request.content,
                    snapshots=self._snapshots,
                    mappings=self._mappings,
                    artifacts=self._artifacts,
                    validation_profile_digest=self._policy.validation_profile_digest,
                )
            guard_execution_deadline(deadline_at)
            content_pub = self._artifacts.put_with_receipt(
                "automatic-release-content-" + content.digest,
                content,
                dependency_hashes=(
                    content.request_digest,
                    content.candidate_manifest_digest,
                    *content.checked_artifact_digests,
                ),
            )
            publications.append(content_pub)
            decision = AutomaticDataReleaseDecisionV1(
                input_digest=input_digest,
                status="passed",
                content_report_digest=content.digest,
                regulatory_evidence_digests=regulatory,
                market_policy_digests=market_policies,
            )
            guard_execution_deadline(deadline_at)
            decision_pub = self._publish_decision(decision)
            publications.append(decision_pub)
            evidence = tuple(
                ArtifactRefV1(
                    artifact_id=publication.artifact.artifact_id,
                    content_hash=publication.artifact.content_hash,
                    media_type=publication.artifact.media_type,
                    role=role,
                )
                for publication, role in (
                    (input_pub, "automatic-release-input-v1"),
                    (content_pub, "automatic-release-content-v1"),
                    (decision_pub, "automatic-release-decision-v1"),
                )
            )
            guard_execution_deadline(deadline_at)
            require_current_parser_action_refs(
                (
                    *request.content.evidence_refs,
                    *(
                        ref
                        for review in request.content.mapping_reviews
                        for ref in review.evidence_refs
                    ),
                ),
                artifacts=self._artifacts,
                build_checks=build_checks,
            )
            guard_execution_deadline(deadline_at)
            verification = sign_data_release_verification(
                {
                    "manifest_digest": request.manifest.manifest_digest,
                    "verification_suite_digest": automatic_release_suite_digest(),
                    "source_revision": self._revision,
                    "verification_run_id": "automatic-release-" + input_digest,
                    "workflow_identity": self._policy.workflow_identity,
                    "verifier_id": self._policy.verifier_id,
                    "passed_gate_ids": tuple(sorted(REQUIRED_DATA_RELEASE_GATES)),
                    "evidence_refs": (*request.content.evidence_refs, *evidence),
                    "mapping_reviews": request.content.mapping_reviews,
                },
                self._key,
            )
            canary = runner.validate(request.manifest, verification)
            guard_execution_deadline(deadline_at)
            canary_pub = self._artifacts.put_with_receipt(
                "automatic-release-canary-" + canary.canary_digest,
                canary,
                dependency_hashes=(
                    sha256_digest(decision),
                    verification.verification_digest,
                ),
            )
            publications.append(canary_pub)
            require_current_parser_action_refs(
                verification.evidence_refs
                + tuple(
                    ref
                    for review in verification.mapping_reviews
                    for ref in review.evidence_refs
                ),
                artifacts=self._artifacts,
                build_checks=build_checks,
            )
            guard_execution_deadline(deadline_at)
            if staged_policies:
                assert self._policy_registry is not None
                for staged_policy in staged_policies:
                    guard_execution_deadline(deadline_at)
                    try:
                        self._policy_registry.add_policy(staged_policy)
                    except PolicyError as error:
                        raise DataReleaseError(error.code, str(error)) from error
            candidate = AutomaticDataReleaseCandidateV1(
                manifest=request.manifest, verification=verification
            )
            guard_execution_deadline(deadline_at)
            candidate_pub = self._artifacts.put_with_receipt(
                "automatic-release-candidate-" + sha256_digest(candidate),
                candidate,
                dependency_hashes=(
                    canary.canary_digest,
                    verification.verification_digest,
                ),
            )
            publications.append(candidate_pub)
            require_current_parser_action_refs(
                verification.evidence_refs
                + tuple(
                    ref
                    for review in verification.mapping_reviews
                    for ref in review.evidence_refs
                ),
                artifacts=self._artifacts,
                build_checks=build_checks,
            )
            guard_execution_deadline(deadline_at)
        except (DataReleaseError, SnapshotError, ValueError) as error:
            if candidate_pub is not None:
                rejected = {
                    "input_digest": input_digest,
                    "candidate": candidate_pub.artifact,
                    "issue_code": getattr(
                        error, "code", "AUTOMATIC_RELEASE_EVIDENCE_INVALID"
                    ),
                }
                publications.append(
                    self._artifacts.put_with_receipt(
                        "automatic-release-rejected-candidate-"
                        + sha256_digest(rejected),
                        rejected,
                        (input_digest, candidate_pub.artifact.content_hash),
                    )
                )
                candidate_pub = None
            decision = AutomaticDataReleaseDecisionV1(
                input_digest=input_digest,
                status="blocked",
                issue_codes=(
                    getattr(error, "code", "AUTOMATIC_RELEASE_EVIDENCE_INVALID"),
                ),
            )
            decision_pub = self._publish_decision(decision)
            publications.append(decision_pub)
        return AutomaticDataReleaseReceiptV1(
            input_digest=input_digest,
            output_digest=sha256_digest(
                {
                    "decision": decision,
                    "candidate": candidate_pub.artifact.content_hash
                    if candidate_pub
                    else None,
                    "canary": canary_pub.artifact.content_hash if canary_pub else None,
                }
            ),
            decision=decision,
            input_publication=input_pub,
            decision_publication=decision_pub,
            candidate_publication=candidate_pub,
            canary_publication=canary_pub,
            wrote=any(item.wrote for item in publications),
        )

    def _publish_decision(
        self, decision: AutomaticDataReleaseDecisionV1
    ) -> ArtifactPublicationV1:
        return self._artifacts.put_with_receipt(
            "automatic-release-decision-" + sha256_digest(decision),
            decision,
            dependency_hashes=(
                decision.input_digest,
                *decision.regulatory_evidence_digests,
                *(
                    (decision.content_report_digest,)
                    if decision.content_report_digest
                    else ()
                ),
            ),
        )
