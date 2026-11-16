"""Provider-neutral reproduction of retained common-share quote evidence."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol

from .equity_dilution import CommonShareQuoteV1, DilutionError


@dataclass(frozen=True)
class QuoteSourceRequestV1:
    """Selection and provenance metadata; the provider must reproduce the price."""

    issuer_id: str
    security_id: str
    source_id: str
    source_version: str
    terms_reference: str
    source_uri: str
    as_of: datetime
    captured_at: datetime


class QuoteSourceProviderPort(Protocol):
    def supports(self, source_id: str, source_version: str) -> bool: ...

    def reproduce_quote(
        self, raw: bytes, *, request: QuoteSourceRequestV1
    ) -> CommonShareQuoteV1: ...


def reproduce_quote_source(
    quote: CommonShareQuoteV1,
    raw: bytes,
    *,
    providers: tuple[QuoteSourceProviderPort, ...],
) -> None:
    """Require one configured provider and an exact source-bound quote match."""
    matches = tuple(
        provider
        for provider in providers
        if provider.supports(quote.source_id, quote.source_version)
    )
    if not matches:
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED",
            "quote requires a configured executable source transcription profile",
        )
    if len(matches) != 1:
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_PROFILE_AMBIGUOUS",
            "multiple providers support the declared quote source profile",
        )
    if sha256(raw).hexdigest() != quote.content_hash:
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_MISMATCH",
            "quote source bytes differ from the declared content hash",
        )
    selected = matches[0].reproduce_quote(
        raw,
        request=QuoteSourceRequestV1(
            issuer_id=quote.issuer_id,
            security_id=quote.security_id,
            source_id=quote.source_id,
            source_version=quote.source_version,
            terms_reference=quote.terms_reference,
            source_uri=quote.source_uri,
            as_of=quote.as_of,
            captured_at=quote.captured_at,
        ),
    )
    if selected != quote:
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_VALUE_MISMATCH",
            "quote value, identity or timestamps differ from retained source selection",
        )
