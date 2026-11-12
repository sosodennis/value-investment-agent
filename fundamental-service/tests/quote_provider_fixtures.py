"""Synthetic quote format used to exercise provider substitution."""

from hashlib import sha256
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from fundamental_service.equity_dilution import CommonShareQuoteV1
from fundamental_service.quote_providers import QuoteSourceRequestV1


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
