"""Pinned issuer operating release publication and serving through shared gates."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .contracts import CanonicalFactV1, SourceSnapshotV1, StrictModel
from .data_releases import (
    DataReleaseError,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    IssuerOperatingReleaseManifestV1,
)
from .facts import CanonicalMappingV1, resolve_canonical_facts
from .operating_forecast import OperatingForecastV1, prepare_operating_forecast
from .original_issuer import IssuerOperatingSourceV1
from .release_runner import (
    DataReleaseCanaryReportV1,
    DataReleaseCanaryRunner,
    ReleaseArtifactReader,
)
from .replay import ArtifactPublicationV1, ArtifactStore
from .serialization import canonical_bytes, sha256_digest


class IssuerOperatingReleaseBundleV1(StrictModel):
    manifest: IssuerOperatingReleaseManifestV1
    verification: DataReleaseVerificationV1
    sources: tuple[IssuerOperatingSourceV1, ...] = Field(min_length=1)
    facts: tuple[CanonicalFactV1, ...] = Field(min_length=1)
    mappings: tuple[CanonicalMappingV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def members_match_manifest(self) -> IssuerOperatingReleaseBundleV1:
        for identities in (
            tuple(item.snapshot_id for item in self.sources),
            tuple(item.fact_id for item in self.facts),
            tuple(item.decision_id for item in self.mappings),
        ):
            if identities != tuple(sorted(set(identities))):
                raise ValueError(
                    "issuer release members must be distinct and canonical"
                )
        if (
            {item.snapshot_id for item in self.sources}
            != {item.snapshot_id for item in self.manifest.snapshot_refs}
            or {item.fact_id for item in self.facts}
            != {
                ref.fact_id
                for source in self.manifest.snapshot_refs
                for ref in source.facts
            }
            or {item.decision_id for item in self.mappings}
            != {item.mapping_id for item in self.manifest.mapping_refs}
        ):
            raise ValueError(
                "issuer release bundle must contain exactly its declared members"
            )
        return self

    @property
    def artifact_id(self) -> str:
        return "issuer-operating-release-" + sha256_digest(self)


class ReleasedOperatingForecastV1(StrictModel):
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canary: DataReleaseCanaryReportV1
    forecast: OperatingForecastV1

    @model_validator(mode="after")
    def release_matches_forecast(self) -> ReleasedOperatingForecastV1:
        if (
            self.manifest_digest != self.canary.candidate_manifest_digest
            or self.manifest_digest != self.forecast.data_release_manifest_digest
            or self.forecast.snapshot_id not in self.canary.checked_snapshot_ids
        ):
            raise ValueError("operating forecast must use its checked release")
        return self


class _SourceReader:
    def __init__(self, bundle: IssuerOperatingReleaseBundleV1) -> None:
        self.sources = {item.snapshot_id: item for item in bundle.sources}

    def get(self, snapshot_id: str) -> IssuerOperatingSourceV1:
        return self.sources[snapshot_id]


class _FactReader:
    def __init__(self, bundle: IssuerOperatingReleaseBundleV1) -> None:
        self.facts = {item.fact_id: item for item in bundle.facts}
        self.mappings = {item.decision_id: item for item in bundle.mappings}

    def get(self, fact_id: str) -> CanonicalFactV1:
        return self.facts[fact_id]

    def list(self) -> tuple[CanonicalFactV1, ...]:
        return tuple(self.facts[key] for key in sorted(self.facts))

    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1:
        return self.mappings[mapping_id]

    def resolve(
        self,
        *,
        snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
        valuation_timestamp: datetime,
        required_fields: tuple[str, ...],
    ) -> tuple[CanonicalFactV1, ...]:
        return resolve_canonical_facts(
            self.list(),
            snapshot=snapshot,
            valuation_timestamp=valuation_timestamp,
            required_fields=required_fields,
        )

    def publish(self, fact: CanonicalFactV1) -> None:
        raise TypeError("released bundle readers cannot publish facts")


class IssuerOperatingReleaseService:
    """Own deployment trust roots; recheck pinned bytes and authority on every read."""

    def __init__(
        self,
        *,
        releases: ArtifactStore,
        evidence: ReleaseArtifactReader,
        trust_roots: DataReleaseTrustRootsV1,
    ) -> None:
        self._releases = releases
        self._evidence = evidence
        self._trust_roots = DataReleaseTrustRootsV1.model_validate_json(
            canonical_bytes(trust_roots)
        )

    def verify(
        self, bundle: IssuerOperatingReleaseBundleV1
    ) -> DataReleaseCanaryReportV1:
        bundle = IssuerOperatingReleaseBundleV1.model_validate_json(
            canonical_bytes(bundle)
        )
        reader = _FactReader(bundle)
        return DataReleaseCanaryRunner(
            snapshot_repository=_SourceReader(bundle),
            fact_repository=reader,
            mapping_reader=reader,
            artifact_reader=self._evidence,
            trust_roots=self._trust_roots,
        ).validate(bundle.manifest, bundle.verification)

    def publish(self, bundle: IssuerOperatingReleaseBundleV1) -> ArtifactPublicationV1:
        bundle = IssuerOperatingReleaseBundleV1.model_validate_json(
            canonical_bytes(bundle)
        )
        report = self.verify(bundle)
        return self._releases.put_with_receipt(
            bundle.artifact_id,
            bundle,
            (
                bundle.manifest.manifest_digest,
                report.canary_digest,
                bundle.verification.verification_digest,
            ),
        )

    def prepare(
        self, *, artifact_id: str, expected_manifest_digest: str, snapshot_id: str
    ) -> ReleasedOperatingForecastV1:
        bundle = IssuerOperatingReleaseBundleV1.model_validate_json(
            self._releases.read(artifact_id)
        )
        if (
            artifact_id != bundle.artifact_id
            or bundle.manifest.manifest_digest != expected_manifest_digest
        ):
            raise DataReleaseError(
                "DATA_RELEASE_PIN_MISMATCH",
                "issuer operating reads require the exact immutable release",
            )
        canary = self.verify(bundle)
        try:
            source = _SourceReader(bundle).get(snapshot_id)
        except KeyError as error:
            raise DataReleaseError(
                "DATA_RELEASE_SNAPSHOT_NOT_IN_RELEASE",
                "requested issuer source is not a member of the pinned release",
            ) from error
        reference = next(
            item
            for item in bundle.manifest.snapshot_refs
            if item.snapshot_id == snapshot_id
        )
        members = {item.fact_id for item in reference.facts}
        facts = tuple(item for item in bundle.facts if item.fact_id in members)
        manifest = bundle.manifest
        forecast = prepare_operating_forecast(
            facts,
            snapshot=source,
            model_id=manifest.model_id,
            model_version=manifest.model_version,
            policy_id=manifest.policy_id,
            policy_version=manifest.policy_version,
            mapping_version=manifest.mapping_version,
            data_release_manifest_digest=manifest.manifest_digest,
        )
        return ReleasedOperatingForecastV1(
            manifest_digest=manifest.manifest_digest, canary=canary, forecast=forecast
        )
