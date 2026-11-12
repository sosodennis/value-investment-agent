"""Provider-neutral issuer classification evidence from retained originals."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .serialization import sha256_digest
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1, SourceArtifactV1


class ClassificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IssuerClassificationRequestV1(ClassificationModel):
    """Exact historical issuer/original scope; no expected classification values."""

    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    report_period_end: date
    valuation_at: datetime

    @field_validator("valuation_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("classification requires a valuation timezone")
        return value.astimezone(UTC)


class IssuerClassificationAttributeV1(ClassificationModel):
    """A source's own classification; not a reference-provider industry mapping."""

    role: Literal["incorporation_jurisdiction", "industry_code"]
    scheme: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_value: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("value", "source_value")
    @classmethod
    def canonical_value(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("classification value must use canonical whitespace")
        return value


class IssuerClassificationObservationV1(ClassificationModel):
    """One dated original, retaining incomplete attributes and amendment identity."""

    provider_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form: Literal["10-K", "10-K/A"]
    report_period_end: date
    accepted_at: datetime
    available_at: datetime
    captured_at: datetime
    artifacts: tuple[SourceArtifactV1, ...] = Field(min_length=1)
    attributes: tuple[IssuerClassificationAttributeV1, ...]
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values: object) -> IssuerClassificationObservationV1:
        return cls.model_validate({**values, "content_digest": sha256_digest(values)})

    @model_validator(mode="after")
    def canonical_evidence(self) -> IssuerClassificationObservationV1:
        times = (self.accepted_at, self.available_at, self.captured_at)
        if any(x.tzinfo is None or x.utcoffset() is None for x in times):
            raise ValueError("classification source dates require timezones")
        if not self.accepted_at <= self.available_at <= self.captured_at:
            raise ValueError("classification source dates are inconsistent")
        if self.report_period_end > self.accepted_at.date():
            raise ValueError("classification report period is after acceptance")
        if (
            self.artifacts != tuple(sorted(self.artifacts, key=sha256_digest))
            or len({(x.source_id, x.uri) for x in self.artifacts})
            != len(self.artifacts)
            or any(x.captured_at > self.captured_at for x in self.artifacts)
        ):
            raise ValueError("classification originals must be canonical and distinct")
        if self.attributes != tuple(sorted(self.attributes, key=lambda x: x.role)):
            raise ValueError("classification attributes must be in canonical order")
        if len({x.role for x in self.attributes}) != len(self.attributes):
            raise ValueError("classification contains duplicate or conflicting roles")
        hashes = {x.content_sha256 for x in self.artifacts}
        if any(x.source_sha256 not in hashes for x in self.attributes):
            raise ValueError("classification attribute lacks its original bytes")
        if self.content_digest != sha256_digest(
            self.model_dump(exclude={"content_digest"})
        ):
            raise ValueError("classification observation digest does not match content")
        return self


class IssuerClassificationProviderPort(Protocol):
    """Reproduce source classifications without I/O, issuer policy or valuation."""

    provider_id: str

    def reproduce_classification(
        self, *, sources: tuple[RetainedSourceV1, ...]
    ) -> IssuerClassificationObservationV1: ...


class IssuerClassificationEvidenceV1(ClassificationModel):
    """Retain the exact request, every source hash, and all stable refusal codes."""

    protocol: Literal["issuer-classification-v1"] = "issuer-classification-v1"
    request: IssuerClassificationRequestV1
    provider_id: str = Field(min_length=1)
    source_artifacts: tuple[SourceArtifactV1, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation: IssuerClassificationObservationV1 | None
    status: Literal["matched", "refused"]
    issue_codes: tuple[str, ...]
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_result(self) -> IssuerClassificationEvidenceV1:
        if self.source_artifacts != tuple(
            sorted(self.source_artifacts, key=sha256_digest)
        ):
            raise ValueError("classification input sources are not canonical")
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("classification issues are not canonical")
        if self.status != ("refused" if self.issue_codes else "matched"):
            raise ValueError("classification status differs from its refusals")
        if self.observation is None:
            if "ISSUER_CLASSIFICATION_REPRODUCTION_FAILED" not in self.issue_codes:
                raise ValueError("classification must retain reproduction failure")
        elif (
            self.observation.provider_id != self.provider_id
            or self.observation.artifacts != self.source_artifacts
            or self.issue_codes != _scope_issues(self.request, self.observation)
        ):
            raise ValueError("classification differs from its original scope")
        if self.input_digest != sha256_digest(
            {
                "protocol": self.protocol,
                "request": self.request,
                "provider_id": self.provider_id,
                "source_artifacts": self.source_artifacts,
            }
        ) or self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("classification evidence digest does not match content")
        return self


def _scope_issues(
    request: IssuerClassificationRequestV1,
    observation: IssuerClassificationObservationV1,
) -> tuple[str, ...]:
    codes = set()
    if observation.issuer_id != request.issuer_id:
        codes.add("ISSUER_CLASSIFICATION_ISSUER_MISMATCH")
    if observation.accession_number != request.accession_number:
        codes.add("ISSUER_CLASSIFICATION_ACCESSION_MISMATCH")
    if observation.report_period_end != request.report_period_end:
        codes.add("ISSUER_CLASSIFICATION_PERIOD_MISMATCH")
    if observation.form != "10-K":
        codes.add("ISSUER_CLASSIFICATION_AMENDMENT_UNSUPPORTED")
    if observation.available_at > request.valuation_at:
        codes.add("ISSUER_CLASSIFICATION_NOT_AVAILABLE")
    roles = {x.role for x in observation.attributes}
    if "industry_code" not in roles:
        codes.add("ISSUER_CLASSIFICATION_INDUSTRY_MISSING")
    if "incorporation_jurisdiction" not in roles:
        codes.add("ISSUER_CLASSIFICATION_JURISDICTION_MISSING")
    return tuple(sorted(codes))


def reproduce_issuer_classification(
    provider: IssuerClassificationProviderPort,
    *,
    request: IssuerClassificationRequestV1,
    sources: tuple[RetainedSourceV1, ...],
    expected: IssuerClassificationEvidenceV1 | None = None,
) -> IssuerClassificationEvidenceV1:
    """Reproduce before comparing; a content digest is never source authority."""
    artifacts = tuple(
        sorted(
            (
                SourceArtifactV1(
                    source_id=x.source_id,
                    uri=x.uri,
                    source_version=x.source_version,
                    terms_reference=x.terms_reference,
                    captured_at=x.captured_at,
                    content_sha256=hashlib.sha256(x.content).hexdigest(),
                )
                for x in sources
            ),
            key=sha256_digest,
        )
    )
    observation = None
    try:
        candidate = provider.reproduce_classification(
            sources=tuple(sorted(sources, key=lambda x: (x.source_id, x.uri)))
        )
        # Validate at the provider boundary, including adapters using model_copy.
        candidate = IssuerClassificationObservationV1.model_validate_json(
            candidate.model_dump_json()
        )
        if (
            candidate.provider_id != provider.provider_id
            or candidate.artifacts != artifacts
        ):
            raise SnapshotError(
                "ISSUER_CLASSIFICATION_PROVIDER_MISMATCH",
                "classification provider did not bind every exact original",
            )
        observation = candidate
        codes = _scope_issues(request, observation)
    except (ValueError, SnapshotError) as error:
        codes = tuple(
            sorted(
                {"ISSUER_CLASSIFICATION_REPRODUCTION_FAILED"}
                | ({error.code} if isinstance(error, SnapshotError) else set())
            )
        )
    inputs = {
        "protocol": "issuer-classification-v1",
        "request": request,
        "provider_id": provider.provider_id,
        "source_artifacts": artifacts,
    }
    payload = {
        **inputs,
        "input_digest": sha256_digest(inputs),
        "observation": observation,
        "status": "refused" if codes else "matched",
        "issue_codes": codes,
    }
    result = IssuerClassificationEvidenceV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
    if expected is not None and result != expected:
        raise SnapshotError(
            "ISSUER_CLASSIFICATION_REPLAY_MISMATCH",
            "classification no longer reproduces its retained original evidence",
        )
    return result
