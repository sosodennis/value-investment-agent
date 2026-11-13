"""Publish exact authorized market policies after the signed release canary."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .automatic_market_policy_evidence import assemble_authorized_market_policy_record
from .command_artifacts import EvidenceArtifactStore
from .contracts import SourceSnapshotV1, StrictModel
from .data_releases import (
    DataReleaseCandidatePublishRequestV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
)
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort
from .policies import PolicyError, PolicyRecordV1, PolicyRegistry, PolicyRepository
from .quote_providers import QuoteSourceProviderPort
from .release_runner import (
    DataReleaseCanaryReportV1,
    DataReleaseCanaryRunner,
    ReleaseMappingReader,
    ReleaseSnapshotReader,
)
from .facts import CanonicalFactRepository
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest
from .source_admission import SourceUsePolicyV1
from .source_admission_evidence import load_release_source_admissions


class MarketPolicyDeploymentEvidenceV1(StrictModel):
    protocol: Literal["market-policy-deployment-v1"] = "market-policy-deployment-v1"
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    authorization_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_roots_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_use_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: PolicyRecordV1
    canary: DataReleaseCanaryReportV1

    @model_validator(mode="after")
    def exact_context(self) -> MarketPolicyDeploymentEvidenceV1:
        if (
            self.policy.data_release_manifest_digest
            != self.canary.candidate_manifest_digest
            or self.source_revision != self.canary.verification.source_revision
            or self.snapshot_id not in self.canary.checked_snapshot_ids
        ):
            raise ValueError("market-policy publication must bind its exact canary")
        return self


class MarketPolicyDeployment:
    """Use deployment-owned authority; source plans cannot authorize policies."""

    def __init__(
        self,
        *,
        policies: PolicyRepository,
        registry: PolicyRegistry,
        snapshots: ReleaseSnapshotReader,
        facts: CanonicalFactRepository,
        mappings: ReleaseMappingReader,
        artifacts: EvidenceArtifactStore,
        trust_roots: DataReleaseTrustRootsV1,
        source_use_policy: SourceUsePolicyV1,
        macro_providers: tuple[MacroSeriesProviderPort, ...],
        reference_providers: tuple[MarketReferenceProviderPort, ...],
        quote_providers: tuple[QuoteSourceProviderPort, ...],
        authorized_organizations: frozenset[str],
        runtime_source_revision: str,
    ) -> None:
        self._policies = policies
        self._registry = registry
        self._snapshots = snapshots
        self._facts = facts
        self._mappings = mappings
        self._artifacts = artifacts
        self._trust_roots = trust_roots
        self._source_use_policy = source_use_policy
        self._macro_providers = macro_providers
        self._reference_providers = reference_providers
        self._quote_providers = quote_providers
        self._authorized_organizations = authorized_organizations
        self._source_revision = runtime_source_revision

    def publish(
        self,
        candidate: DataReleaseCandidatePublishRequestV1,
        *,
        authorization: PolicyRecordV1,
        authorization_digest: str,
        snapshot_id: str,
        organization_id: str,
    ) -> tuple[MarketPolicyDeploymentEvidenceV1, ArtifactPublicationV1]:
        candidate = DataReleaseCandidatePublishRequestV1.model_validate_json(
            canonical_bytes(candidate)
        )
        authorization = PolicyRecordV1.model_validate_json(
            canonical_bytes(authorization)
        )
        if organization_id not in self._authorized_organizations:
            raise DataReleaseError(
                "DATA_RELEASE_FORBIDDEN", "organization cannot publish market policies"
            )
        if sha256_digest(authorization) != authorization_digest:
            raise DataReleaseError(
                "MARKET_POLICY_AUTHORIZATION_MISMATCH",
                "operator authorization differs from its pinned digest",
            )
        if candidate.verification.source_revision != self._source_revision:
            raise DataReleaseError(
                "AUTOMATIC_MARKET_POLICY_REVISION_MISMATCH",
                "signed candidate differs from the installed runtime revision",
            )
        manifest = candidate.manifest
        refs = tuple(
            item for item in manifest.snapshot_refs if item.snapshot_id == snapshot_id
        )
        if len(refs) != 1:
            raise DataReleaseError(
                "MARKET_POLICY_SNAPSHOT_MISMATCH",
                "market policy requires one exact released security snapshot",
            )
        snapshot = self._snapshots.get(snapshot_id)
        if (
            not isinstance(snapshot, SourceSnapshotV1)
            or refs[0].manifest_digest != snapshot.manifest_digest
        ):
            raise DataReleaseError(
                "MARKET_POLICY_SNAPSHOT_MISMATCH",
                "market policy requires the exact released security snapshot",
            )
        model = self._registry.model(
            authorization.model_id, authorization.model_version
        )
        if model is None:
            raise DataReleaseError(
                "MODEL_UNSUPPORTED", "deployment model is unavailable"
            )
        admissions = load_release_source_admissions(
            manifest,
            artifacts=self._artifacts,
            policy=self._source_use_policy,
            macro_providers=self._macro_providers,
            reference_providers=self._reference_providers,
        )
        policy = assemble_authorized_market_policy_record(
            manifest,
            authorization=authorization,
            model=model,
            snapshot=snapshot,
            admissions=admissions,
            artifacts=self._artifacts,
            expected_source_revision=self._source_revision,
        )
        published = self._policies.list()
        if any(
            item.policy_id == policy.policy_id and item != policy for item in published
        ):
            raise DataReleaseError(
                "POLICY_IMMUTABLE", "published policy identities cannot be replaced"
            )
        staged = PolicyRegistry(
            models=(model,),
            policies=(
                *tuple(
                    item
                    for item in self._registry.policies()
                    if item.policy_id != policy.policy_id
                ),
                policy,
            ),
        )
        canary = DataReleaseCanaryRunner(
            snapshot_repository=self._snapshots,
            fact_repository=self._facts,
            mapping_reader=self._mappings,
            artifact_reader=self._artifacts,
            trust_roots=self._trust_roots,
            source_use_policy=self._source_use_policy,
            macro_providers=self._macro_providers,
            reference_providers=self._reference_providers,
            quote_providers=self._quote_providers,
            policy_registry=staged,
        ).validate(manifest, candidate.verification)
        evidence = MarketPolicyDeploymentEvidenceV1(
            source_revision=self._source_revision,
            authorization_digest=authorization_digest,
            trust_roots_digest=sha256_digest(self._trust_roots),
            source_use_policy_digest=sha256_digest(self._source_use_policy),
            snapshot_id=snapshot_id,
            snapshot_manifest_digest=snapshot.manifest_digest,
            policy=policy,
            canary=canary,
        )
        try:
            self._policies.publish(policy)
        except PolicyError as error:
            raise DataReleaseError(error.code, str(error)) from error
        digest = sha256_digest(evidence)
        publication = self._artifacts.put_with_receipt(
            f"market-policy-deployment:{digest}",
            evidence,
            (
                authorization_digest,
                policy.policy_digest,
                manifest.manifest_digest,
                canary.canary_digest,
            ),
        )
        return evidence, publication
