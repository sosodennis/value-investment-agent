"""Synthetic quote format used to exercise provider substitution."""

from hashlib import sha256
from decimal import Decimal
from dataclasses import replace

from pydantic import BaseModel, ConfigDict, Field

from fundamental_service.equity_dilution import CommonShareQuoteV1
from fundamental_service.quote_providers import QuoteSourceRequestV1
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.quote_admission import (
    QUOTE_ADMISSION_ROLE,
    QUOTE_TERMS_ROLE,
    QUOTE_METRIC,
    QUOTE_POPULATION,
    admit_quote_source,
)
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseManifestV1
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
)
from fundamental_service.source_evidence import RetainedSourceV1


class _SyntheticQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class SyntheticQuoteProvider:
    def supports(self, source_id: str, source_version: str) -> bool:
        return (
            source_id == "synthetic-quote-vendor" and source_version == "synthetic-v1"
        )

    def reproduce_quote(
        self, raw: bytes, *, request: QuoteSourceRequestV1
    ) -> CommonShareQuoteV1:
        decoded = _SyntheticQuote.model_validate_json(raw)
        return CommonShareQuoteV1(
            issuer_id=request.issuer_id,
            security_id=request.security_id,
            currency=decoded.currency,
            price=decoded.price,
            source_id=request.source_id,
            source_uri=request.source_uri,
            source_version=request.source_version,
            terms_reference=request.terms_reference,
            content_hash=sha256(raw).hexdigest(),
            as_of=request.as_of,
            available_at=request.captured_at,
            captured_at=request.captured_at,
        )


def publish_synthetic_quote_admission(
    quote, raw, *, valuation_at, artifacts, base_policy=None
):
    """An explicit test grant; these bytes authorize no real upstream data."""
    terms = RetainedSourceV1(
        source_id="synthetic-quote-terms",
        uri="https://example.test/synthetic-quote-permission",
        source_version="synthetic-test-only-v1",
        terms_reference="synthetic-test-only",
        content=b"Synthetic quote fixture permission; no actual source rights.",
        captured_at=quote.captured_at,
    )
    base = base_policy or free_market_source_policy()
    rule = SourceUseRuleV1(
        rule_id="synthetic-quote-use",
        provider_id=quote.source_id,
        metric_id=QUOTE_METRIC,
        population=QUOTE_POPULATION,
        source_id=quote.source_id,
        source_version=quote.source_version,
        terms_reference=quote.terms_reference,
        permitted_uses=("valuation_preparation",),
        terms=(
            TermsRequirementV1(
                uri=terms.uri, content_sha256=sha256(terms.content).hexdigest()
            ),
        ),
        required_notices=("Synthetic test-only source permission",),
        basis="Explicit permission for synthetic fixture bytes only",
    )
    policy = SourceUsePolicyV1(
        policy_version="synthetic-quote-use-v1",
        rules=tuple(
            sorted(
                (*(r for r in base.rules if r.rule_id != rule.rule_id), rule),
                key=lambda r: r.rule_id,
            )
        ),
    )
    admission = admit_quote_source(
        quote,
        raw,
        providers=(*default_quote_providers(), SyntheticQuoteProvider()),
        terms=(terms,),
        policy=policy,
        valuation_at=valuation_at,
    )
    assert admission.status == "admitted"
    refs = []
    for role, content, media in (
        (QUOTE_ADMISSION_ROLE, canonical_bytes(admission), "application/json"),
        (QUOTE_TERMS_ROLE, terms.content, "text/plain"),
    ):
        digest = sha256(content).hexdigest()
        identifier = role + ":" + digest
        artifacts.put_bytes_with_receipt(identifier, content, media_type=media)
        refs.append(
            ArtifactRefV1(
                artifact_id=identifier, content_hash=digest, media_type=media, role=role
            )
        )
    return policy, tuple(refs)


def bind_synthetic_quote_permission(fixture, base_policy):
    """Rebind the quote when a test explicitly installs a different source policy."""
    from equity_award_fixtures import quote_source_bytes

    policy, refs = publish_synthetic_quote_admission(
        fixture.dilution.quote,
        quote_source_bytes(fixture.snapshot),
        valuation_at=fixture.snapshot.valuation_timestamp,
        artifacts=fixture.artifacts,
        base_policy=base_policy,
    )
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (
        tuple(
            ref
            for ref in fixture.manifest.artifact_refs
            if ref.role not in {QUOTE_ADMISSION_ROLE, QUOTE_TERMS_ROLE}
        )
        + refs
    )
    fixture.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    fixture.application = replace(fixture.application, source_use_policy=policy)
    return policy
