"""Prepare source-use decisions from verified public acquisition receipts."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort, ReferenceMetric
from .public_acquisition import PublicSourceAcquisitionEvidenceV1
from .quote_admission import (
    QUOTE_ADMISSION_ROLE,
    QUOTE_METRIC,
    QUOTE_TERMS_ROLE,
    EQUITY_QUOTE_SOURCE_ROLE,
    QuoteAdmissionV1,
    admit_quote_source,
)
from .quote_providers import QuoteSourceProviderPort, QuoteSourceRequestV1
from .replay import ArtifactPublicationV1
from .serialization import sha256_digest
from .source_admission import (
    SourceAdmissionV1,
    SourceUse,
    SourceUsePolicyV1,
    admit_macro_source,
    admit_reference_source,
)
from .source_admission_evidence import (
    SOURCE_ADMISSION_ROLE,
    SOURCE_ORIGINAL_ROLE,
    SOURCE_TERMS_ROLE,
)
from .source_evidence import RetainedSourceV1
from .equity_dilution import DilutionError


ContentDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PublicQuoteSelectionV1(StrictModel):
    issuer_id: str = Field(min_length=1)
    security_id: str = Field(min_length=1)
    as_of: AwareDatetime


class PublicSourceAdmissionRequestV1(StrictModel):
    protocol: Literal["public-source-admission-v1"] = "public-source-admission-v1"
    kind: Literal["macro", "reference", "quote"]
    provider_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    intended_use: SourceUse = "valuation_preparation"
    valuation_at: AwareDatetime
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_request_digests: tuple[ContentDigest, ...] = Field(
        min_length=1, max_length=8
    )
    terms_request_digests: tuple[ContentDigest, ...] = Field(default=(), max_length=8)
    quote_selection: PublicQuoteSelectionV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def canonical_requests(self) -> PublicSourceAdmissionRequestV1:
        for items in (self.source_request_digests, self.terms_request_digests):
            if items != tuple(sorted(set(items))):
                raise ValueError("admission capture digests must be canonical")
        if set(self.source_request_digests) & set(self.terms_request_digests):
            raise ValueError("source and terms captures must be distinct")
        if self.kind == "reference":
            TypeAdapter(ReferenceMetric).validate_python(self.metric_id)
        if self.kind == "quote":
            if (
                self.quote_selection is None
                or self.metric_id != QUOTE_METRIC
                or len(self.source_request_digests) != 1
                or self.quote_selection.as_of > self.valuation_at
            ):
                raise ValueError("quote admission requires one dated source selection")
        elif self.quote_selection is not None:
            raise ValueError("only quote admission accepts a quote selection")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class PublicSourceAdmissionEvidenceV1(StrictModel):
    protocol: Literal["public-source-admission-evidence-v1"] = (
        "public-source-admission-evidence-v1"
    )
    request: PublicSourceAdmissionRequestV1
    acquisition_refs: tuple[ArtifactRefV1, ...]
    source_refs: tuple[ArtifactRefV1, ...]
    terms_refs: tuple[ArtifactRefV1, ...]
    admission: SourceAdmissionV1 | QuoteAdmissionV1 | None
    issue_codes: tuple[str, ...]

    @model_validator(mode="after")
    def canonical_evidence(self) -> PublicSourceAdmissionEvidenceV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("source admission issues must be canonical")
        for items, role in (
            (self.acquisition_refs, "public-source-acquisition-evidence-v1"),
            (
                self.source_refs,
                EQUITY_QUOTE_SOURCE_ROLE
                if self.request.kind == "quote"
                else SOURCE_ORIGINAL_ROLE,
            ),
            (
                self.terms_refs,
                QUOTE_TERMS_ROLE if self.request.kind == "quote" else SOURCE_TERMS_ROLE,
            ),
        ):
            if items != tuple(sorted(items, key=lambda ref: ref.artifact_id)) or len(
                {ref.artifact_id for ref in items}
            ) != len(items):
                raise ValueError("source admission references must be canonical")
            if any(ref.role != role for ref in items):
                raise ValueError("source admission reference has the wrong role")
        if self.admission is None:
            if not self.issue_codes:
                raise ValueError("unreproduced admission requires a refusal")
        elif isinstance(self.admission, QuoteAdmissionV1):
            expected = self.request
            quote_request = self.admission.request
            selection = expected.quote_selection
            quote = quote_request.quote
            if (
                expected.kind != "quote"
                or selection is None
                or quote.issuer_id != selection.issuer_id
                or quote.security_id != selection.security_id
                or quote.as_of != selection.as_of
                or quote.source_id != expected.provider_id
                or any(
                    getattr(expected, field) != getattr(quote_request, field)
                    for field in (
                        "intended_use",
                        "valuation_at",
                        "policy_version",
                        "policy_digest",
                    )
                )
                or not set(self.admission.issue_codes) <= set(self.issue_codes)
                or {ref.content_hash for ref in self.source_refs}
                != {quote_request.source_content_sha256}
                or {ref.content_hash for ref in self.terms_refs}
                != {item.content_sha256 for item in quote_request.terms_artifacts}
            ):
                raise ValueError(
                    "quote admission differs from its captures or selection"
                )
        else:
            expected = self.request
            actual = self.admission.request
            if any(
                getattr(expected, field) != getattr(actual, field)
                for field in (
                    "kind",
                    "provider_id",
                    "metric_id",
                    "intended_use",
                    "valuation_at",
                    "policy_version",
                    "policy_digest",
                )
            ) or not set(self.admission.issue_codes) <= set(self.issue_codes):
                raise ValueError(
                    "source admission differs from its preparation request"
                )
            for artifacts, refs in (
                (actual.source_artifacts, self.source_refs),
                (actual.terms_artifacts, self.terms_refs),
            ):
                if {item.content_sha256 for item in artifacts} != {
                    ref.content_hash for ref in refs
                }:
                    raise ValueError("source admission omits original references")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def release_refs(self) -> tuple[ArtifactRefV1, ...]:
        if self.admission is None or self.issue_codes:
            return ()
        return (
            ArtifactRefV1(
                artifact_id=f"{'quote' if self.request.kind == 'quote' else 'source'}-admission:{self.admission.output_digest}",
                content_hash=sha256_digest(self.admission),
                media_type="application/json",
                role=QUOTE_ADMISSION_ROLE
                if self.request.kind == "quote"
                else SOURCE_ADMISSION_ROLE,
            ),
            *self.source_refs,
            *self.terms_refs,
        )


class PublicAcquisitionReader(Protocol):
    def read(self, artifact_id: str) -> PublicSourceAcquisitionEvidenceV1: ...

    def retained_source(
        self, evidence: PublicSourceAcquisitionEvidenceV1
    ) -> RetainedSourceV1: ...


class AdmissionArtifactWriter(Protocol):
    def put_with_receipt(
        self, artifact_id: str, value: object, dependency_hashes: tuple[str, ...] = ()
    ) -> ArtifactPublicationV1: ...

    def put_bytes_with_receipt(
        self,
        artifact_id: str,
        payload: bytes,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/octet-stream",
    ) -> ArtifactPublicationV1: ...


class PublicSourceAdmission:
    def __init__(
        self,
        *,
        acquisitions: PublicAcquisitionReader,
        artifacts: AdmissionArtifactWriter,
        policy: SourceUsePolicyV1,
        macro_providers: tuple[MacroSeriesProviderPort, ...] = (),
        reference_providers: tuple[MarketReferenceProviderPort, ...] = (),
        quote_providers: tuple[QuoteSourceProviderPort, ...] = (),
    ) -> None:
        self._acquisitions = acquisitions
        self._artifacts = artifacts
        self._policy = policy
        self._macro_providers = macro_providers
        self._reference_providers = reference_providers
        self._quote_providers = quote_providers

    def execute(
        self,
        request: PublicSourceAdmissionRequestV1,
        captures: tuple[PublicSourceAcquisitionEvidenceV1, ...],
    ) -> tuple[PublicSourceAdmissionEvidenceV1, ArtifactPublicationV1]:
        by_request = {item.request.digest: item for item in captures}
        if len(by_request) != len(captures):
            raise ValueError("source admission repeats a capture request")
        selected = []
        for digest in sorted(
            (*request.source_request_digests, *request.terms_request_digests)
        ):
            if digest not in by_request:
                raise ValueError("source admission is missing a pinned capture")
            supplied = by_request[digest]
            retained = self._acquisitions.read(supplied.artifact_id)
            if (
                retained != supplied
                or retained.request.valuation_timestamp > request.valuation_at
            ):
                raise ValueError(
                    "source admission capture differs from its pinned input"
                )
            selected.append(retained)

        acquisition_refs: list[ArtifactRefV1] = []
        source_refs: list[ArtifactRefV1] = []
        terms_refs: list[ArtifactRefV1] = []
        sources: list[RetainedSourceV1] = []
        terms: list[RetainedSourceV1] = []
        codes = {
            code for item in selected for code in item.issues_at(request.valuation_at)
        }
        for item in selected:
            acquisition_refs.append(
                ArtifactRefV1(
                    artifact_id=item.artifact_id,
                    content_hash=item.digest,
                    media_type="application/json",
                    role=item.protocol,
                )
            )
            if item.source is None:
                continue
            original = self._acquisitions.retained_source(item)
            assert item.media_type is not None
            publication = self._artifacts.put_bytes_with_receipt(
                f"public-source-original:{item.source.content_sha256}:{sha256_digest(item.media_type)}",
                original.content,
                media_type=item.media_type,
            )
            is_source = item.request.digest in request.source_request_digests
            ref = ArtifactRefV1(
                artifact_id=publication.artifact.artifact_id,
                content_hash=publication.artifact.content_hash,
                media_type=publication.artifact.media_type,
                role=(EQUITY_QUOTE_SOURCE_ROLE if is_source else QUOTE_TERMS_ROLE)
                if request.kind == "quote"
                else (SOURCE_ORIGINAL_ROLE if is_source else SOURCE_TERMS_ROLE),
            )
            (sources if is_source else terms).append(original)
            (source_refs if is_source else terms_refs).append(ref)

        admission: SourceAdmissionV1 | QuoteAdmissionV1 | None = None
        if (
            request.policy_version != self._policy.policy_version
            or request.policy_digest != self._policy.digest
        ):
            codes.add("SOURCE_ADMISSION_POLICY_MISMATCH")
        elif any(item.source is None for item in selected):
            codes.add("SOURCE_ADMISSION_CAPTURE_FAILED")
        else:
            if request.kind == "macro":
                providers = tuple(
                    provider
                    for provider in self._macro_providers
                    if provider.provider_id == request.provider_id
                    and provider.supports(request.metric_id)
                )
                if len(providers) == 1:
                    admission = admit_macro_source(
                        providers[0],
                        series_id=request.metric_id,
                        sources=tuple(sources),
                        terms=tuple(terms),
                        policy=self._policy,
                        valuation_at=request.valuation_at,
                        intended_use=request.intended_use,
                    )
            elif request.kind == "reference":
                metric = TypeAdapter(ReferenceMetric).validate_python(request.metric_id)
                reference_providers = tuple(
                    provider
                    for provider in self._reference_providers
                    if provider.provider_id == request.provider_id
                    and provider.supports(metric)
                )
                if len(reference_providers) == 1:
                    admission = admit_reference_source(
                        reference_providers[0],
                        metric=metric,
                        sources=tuple(sources),
                        terms=tuple(terms),
                        policy=self._policy,
                        valuation_at=request.valuation_at,
                        intended_use=request.intended_use,
                    )
            else:
                selection = request.quote_selection
                assert selection is not None
                original = sources[0]
                quote_providers = tuple(
                    provider
                    for provider in self._quote_providers
                    if provider.supports(original.source_id, original.source_version)
                )
                if original.source_id != request.provider_id:
                    codes.add("SOURCE_ADMISSION_PROVIDER_MISMATCH")
                elif len(quote_providers) != 1:
                    codes.add("SOURCE_ADMISSION_PROVIDER_UNAVAILABLE")
                else:
                    try:
                        quote = quote_providers[0].reproduce_quote(
                            original.content,
                            request=QuoteSourceRequestV1(
                                issuer_id=selection.issuer_id,
                                security_id=selection.security_id,
                                source_id=original.source_id,
                                source_version=original.source_version,
                                terms_reference=original.terms_reference,
                                source_uri=original.uri,
                                as_of=selection.as_of,
                                captured_at=original.captured_at,
                            ),
                        )
                        if quote.as_of != selection.as_of:
                            raise DilutionError(
                                "DILUTION_QUOTE_SOURCE_VALUE_MISMATCH",
                                "quote as-of differs from its exact selection",
                            )
                        admission = admit_quote_source(
                            quote,
                            original.content,
                            providers=self._quote_providers,
                            terms=tuple(terms),
                            policy=self._policy,
                            valuation_at=request.valuation_at,
                            intended_use=request.intended_use,
                        )
                    except ValueError as error:
                        codes.add("SOURCE_REPRODUCTION_FAILED")
                        if isinstance(error, DilutionError):
                            codes.add(error.code)
            if admission is None:
                if request.kind != "quote" or not codes:
                    codes.add("SOURCE_ADMISSION_PROVIDER_UNAVAILABLE")
        if admission is not None:
            codes.update(admission.issue_codes)
            self._artifacts.put_with_receipt(
                f"{'quote' if request.kind == 'quote' else 'source'}-admission:{admission.output_digest}",
                admission,
                (
                    admission.input_digest,
                    self._policy.digest,
                    *(ref.content_hash for ref in (*source_refs, *terms_refs)),
                ),
            )

        def ordered(refs: list[ArtifactRefV1]) -> tuple[ArtifactRefV1, ...]:
            return tuple(
                sorted(
                    {ref.artifact_id: ref for ref in refs}.values(),
                    key=lambda ref: ref.artifact_id,
                )
            )

        result = PublicSourceAdmissionEvidenceV1(
            request=request,
            acquisition_refs=ordered(acquisition_refs),
            source_refs=ordered(source_refs),
            terms_refs=ordered(terms_refs),
            admission=admission,
            issue_codes=tuple(sorted(codes)),
        )
        publication = self._artifacts.put_with_receipt(
            f"public-source-admission:{result.digest}",
            result,
            (
                request.digest,
                self._policy.digest,
                *(ref.content_hash for ref in result.acquisition_refs),
                *((sha256_digest(admission),) if admission else ()),
            ),
        )
        return result, publication
