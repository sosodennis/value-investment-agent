"""Reproduce signed-release source admissions from their retained originals."""

from hashlib import sha256
from typing import Protocol

from pydantic import TypeAdapter

from .data_releases import DataReleaseError, DataReleaseManifestV1
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort, ReferenceMetric
from .serialization import canonical_bytes
from .snapshots import SnapshotError
from .source_admission import (
    SourceAdmissionV1,
    SourceUsePolicyV1,
    admit_macro_source,
    admit_reference_source,
)
from .source_evidence import RetainedSourceV1, SourceArtifactV1

SOURCE_ADMISSION_ROLE = "market_source_admission"
SOURCE_ORIGINAL_ROLE = "market_source_original"
SOURCE_TERMS_ROLE = "market_source_terms"


class AdmissionArtifactReader(Protocol):
    def read(self, artifact_id: str) -> bytes: ...


def _load_release_source_admissions(
    manifest: DataReleaseManifestV1,
    *,
    artifacts: AdmissionArtifactReader,
    policy: SourceUsePolicyV1 | None,
    macro_providers: tuple[MacroSeriesProviderPort, ...],
    reference_providers: tuple[MarketReferenceProviderPort, ...],
) -> tuple[SourceAdmissionV1, ...]:
    """Check each declaration without granting complete market-policy authority."""
    admissions = []

    def original(item: SourceArtifactV1, role: str) -> RetainedSourceV1:
        matches = sorted(
            (
                ref
                for ref in manifest.artifact_refs
                if ref.role == role and ref.content_hash == item.content_sha256
            ),
            key=lambda x: x.artifact_id,
        )
        if not matches:
            raise DataReleaseError(
                "SOURCE_ADMISSION_ORIGINAL_MISSING",
                "source admission original is absent from the pinned release",
            )
        raw = artifacts.read(matches[0].artifact_id)
        if sha256(raw).hexdigest() != item.content_sha256:
            raise DataReleaseError(
                "SOURCE_ADMISSION_ORIGINAL_MISMATCH",
                "source admission original differs from the pinned release",
            )
        return RetainedSourceV1(
            source_id=item.source_id,
            uri=item.uri,
            source_version=item.source_version,
            terms_reference=item.terms_reference,
            captured_at=item.captured_at,
            content=raw,
        )

    for ref in sorted(manifest.artifact_refs, key=lambda x: x.artifact_id):
        if ref.role != SOURCE_ADMISSION_ROLE:
            continue
        if policy is None:
            raise DataReleaseError(
                "SOURCE_ADMISSION_POLICY_UNAVAILABLE",
                "source admission requires a configured trusted policy",
            )
        raw = artifacts.read(ref.artifact_id)
        if (
            ref.media_type != "application/json"
            or sha256(raw).hexdigest() != ref.content_hash
        ):
            raise DataReleaseError(
                "SOURCE_ADMISSION_ARTIFACT_MISMATCH",
                "source admission differs from the pinned release",
            )
        admission = SourceAdmissionV1.model_validate_json(raw)
        if canonical_bytes(admission) != raw:
            raise DataReleaseError(
                "SOURCE_ADMISSION_NONCANONICAL",
                "source admission requires canonical serialization",
            )
        request = admission.request
        sources = tuple(
            original(x, SOURCE_ORIGINAL_ROLE) for x in request.source_artifacts
        )
        terms = tuple(original(x, SOURCE_TERMS_ROLE) for x in request.terms_artifacts)
        if request.kind == "macro":
            providers = tuple(
                x
                for x in macro_providers
                if x.provider_id == request.provider_id
                and x.supports(request.metric_id)
            )
            if len(providers) != 1:
                raise DataReleaseError(
                    "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE",
                    "source admission requires exactly one configured provider",
                )
            admit_macro_source(
                providers[0],
                series_id=request.metric_id,
                sources=sources,
                terms=terms,
                valuation_at=request.valuation_at,
                intended_use=request.intended_use,
                policy=policy,
                expected=admission,
            )
        else:
            metric = TypeAdapter(ReferenceMetric).validate_python(request.metric_id)
            reference_matches = tuple(
                x
                for x in reference_providers
                if x.provider_id == request.provider_id and x.supports(metric)
            )
            if len(reference_matches) != 1:
                raise DataReleaseError(
                    "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE",
                    "source admission requires exactly one configured provider",
                )
            admit_reference_source(
                reference_matches[0],
                metric=metric,
                sources=sources,
                terms=terms,
                valuation_at=request.valuation_at,
                intended_use=request.intended_use,
                policy=policy,
                expected=admission,
            )
        if admission.status != "admitted":
            raise DataReleaseError(
                "SOURCE_ADMISSION_REFUSED",
                "a refused source cannot authorize release inputs",
            )
        admissions.append(admission)
    digests = [x.output_digest for x in admissions]
    if len(set(digests)) != len(digests):
        raise DataReleaseError(
            "SOURCE_ADMISSION_DUPLICATE", "release repeats a source admission"
        )
    return tuple(admissions)


def load_release_source_admissions(
    manifest: DataReleaseManifestV1,
    *,
    artifacts: AdmissionArtifactReader,
    policy: SourceUsePolicyV1 | None,
    macro_providers: tuple[MacroSeriesProviderPort, ...],
    reference_providers: tuple[MarketReferenceProviderPort, ...],
) -> tuple[SourceAdmissionV1, ...]:
    """Keep source/parser/storage failures within the release error contract."""
    try:
        return _load_release_source_admissions(
            manifest,
            artifacts=artifacts,
            policy=policy,
            macro_providers=macro_providers,
            reference_providers=reference_providers,
        )
    except SnapshotError as error:
        raise DataReleaseError(error.code, str(error)) from error
    except ValueError as error:
        raise DataReleaseError(
            "SOURCE_ADMISSION_INVALID",
            "source admission violates its evidence contract",
        ) from error
