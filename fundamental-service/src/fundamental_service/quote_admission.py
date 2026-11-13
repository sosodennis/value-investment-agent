"""Reproduce a quote and its intended-use permission without external I/O."""

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from .equity_dilution import CommonShareQuoteV1, DilutionError, DilutionModel
from .quote_providers import QuoteSourceProviderPort, reproduce_quote_source
from .serialization import sha256_digest
from .source_admission import (
    SourceUse,
    SourceUseCheckV1,
    SourceUsePolicyV1,
    check_source_use,
)
from .source_evidence import RetainedSourceV1, SourceArtifactV1

QUOTE_ADMISSION_ROLE: Literal["equity-quote-source-admission-v1"] = (
    "equity-quote-source-admission-v1"
)
QUOTE_TERMS_ROLE = "equity-quote-source-terms-v1"
EQUITY_QUOTE_SOURCE_ROLE = "equity-dilution-quote-source-v1"
QUOTE_METRIC = "common_share.price"
QUOTE_POPULATION = "common-share"


def quote_source_artifact(quote: CommonShareQuoteV1) -> SourceArtifactV1:
    return SourceArtifactV1(
        source_id=quote.source_id,
        uri=quote.source_uri,
        source_version=quote.source_version,
        terms_reference=quote.terms_reference,
        content_sha256=quote.content_hash,
        captured_at=quote.captured_at,
    )


class QuoteAdmissionRequestV1(DilutionModel):
    quote: CommonShareQuoteV1
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    valuation_at: datetime
    intended_use: SourceUse
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    terms_artifacts: tuple[SourceArtifactV1, ...]

    @model_validator(mode="after")
    def canonical_request(self) -> "QuoteAdmissionRequestV1":
        if self.valuation_at.tzinfo is None or self.valuation_at.utcoffset() is None:
            raise ValueError("quote admission requires a valuation timezone")
        keys = tuple(sha256_digest(item) for item in self.terms_artifacts)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("quote terms must have distinct canonical identities")
        return self


class QuoteAdmissionV1(DilutionModel):
    protocol: Literal["equity-quote-source-admission-v1"] = QUOTE_ADMISSION_ROLE
    request: QuoteAdmissionRequestV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_check: SourceUseCheckV1 | None
    status: Literal["admitted", "refused"]
    issue_codes: tuple[str, ...]
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_decision(self) -> "QuoteAdmissionV1":
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("quote admission issues must be distinct and ordered")
        if self.status != ("refused" if self.issue_codes else "admitted"):
            raise ValueError("quote admission status differs from its issues")
        if self.source_check is None:
            if "SOURCE_REPRODUCTION_FAILED" not in self.issue_codes:
                raise ValueError("unreproduced quote must retain its failure")
        else:
            if self.request.source_content_sha256 != self.request.quote.content_hash:
                raise ValueError("reproduced quote does not match its original bytes")
            if self.source_check.artifact_digest != sha256_digest(
                quote_source_artifact(self.request.quote)
            ):
                raise ValueError("quote admission does not cover its original")
            expected_codes = set(self.source_check.issue_codes)
            if self.request.quote.available_at > self.request.valuation_at:
                expected_codes.add("SOURCE_NOT_AVAILABLE_AT_VALUATION")
            if any(
                item.captured_at > self.request.valuation_at
                for item in self.request.terms_artifacts
            ):
                expected_codes.add("SOURCE_USE_TERMS_NOT_AVAILABLE_AT_VALUATION")
            if self.issue_codes != tuple(sorted(expected_codes)):
                raise ValueError("quote admission omits a retained refusal")
        if self.input_digest != sha256_digest(self.request) or self.output_digest != (
            sha256_digest(self.model_dump(exclude={"output_digest"}))
        ):
            raise ValueError("quote admission digests differ from its content")
        return self


def admit_quote_source(
    quote: CommonShareQuoteV1,
    raw: bytes,
    *,
    providers: tuple[QuoteSourceProviderPort, ...],
    terms: tuple[RetainedSourceV1, ...],
    policy: SourceUsePolicyV1,
    valuation_at: datetime,
    intended_use: SourceUse = "valuation_preparation",
    expected: QuoteAdmissionV1 | None = None,
) -> QuoteAdmissionV1:
    """Retain permission and reproduction failures; a parser grants no rights."""
    request = QuoteAdmissionRequestV1(
        quote=quote,
        source_content_sha256=sha256(raw).hexdigest(),
        valuation_at=valuation_at,
        intended_use=intended_use,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        terms_artifacts=tuple(
            sorted(
                (
                    SourceArtifactV1(
                        source_id=item.source_id,
                        uri=item.uri,
                        source_version=item.source_version,
                        terms_reference=item.terms_reference,
                        captured_at=item.captured_at,
                        content_sha256=sha256(item.content).hexdigest(),
                    )
                    for item in terms
                ),
                key=sha256_digest,
            )
        ),
    )
    codes = set()
    check = None
    try:
        reproduce_quote_source(quote, raw, providers=providers)
    except ValueError as error:
        codes.add("SOURCE_REPRODUCTION_FAILED")
        if isinstance(error, DilutionError):
            codes.add(error.code)
    else:
        check = check_source_use(
            provider_id=quote.source_id,
            metric_id=QUOTE_METRIC,
            population=QUOTE_POPULATION,
            artifact=quote_source_artifact(quote),
            intended_use=intended_use,
            terms=terms,
            policy=policy,
        )
        codes.update(check.issue_codes)
        if quote.available_at > valuation_at:
            codes.add("SOURCE_NOT_AVAILABLE_AT_VALUATION")
        if any(item.captured_at > valuation_at for item in terms):
            codes.add("SOURCE_USE_TERMS_NOT_AVAILABLE_AT_VALUATION")
    payload = {
        "protocol": QUOTE_ADMISSION_ROLE,
        "request": request,
        "input_digest": sha256_digest(request),
        "source_check": check,
        "status": "refused" if codes else "admitted",
        "issue_codes": tuple(sorted(codes)),
    }
    result = QuoteAdmissionV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
    if expected is not None and result != expected:
        raise DilutionError(
            "DILUTION_QUOTE_ADMISSION_REPLAY_MISMATCH",
            "quote admission differs from reproduced source permission",
        )
    return result
