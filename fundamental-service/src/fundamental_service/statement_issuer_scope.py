from __future__ import annotations

import re

from .contracts import SecCapturedSourceEvidenceV1, SourceRole
from .data_releases import DataReleaseError
from .issuer_classification import (
    IssuerClassificationEvidenceV1,
    IssuerClassificationRequestV1,
    reproduce_issuer_classification,
)
from .sec_classification_source import (
    SEC_CLASSIFICATION_PROFILE,
    SEC_CLASSIFICATION_SOURCE,
    SecSubmissionClassificationProvider,
)
from .sec_source import SEC_TERMS
from .snapshots import ContentAddressedStore
from .source_evidence import RetainedSourceV1


def reproduce_statement_issuer_classification(
    *,
    request: IssuerClassificationRequestV1,
    captured_sources: tuple[SecCapturedSourceEvidenceV1, ...],
    content: ContentAddressedStore,
) -> IssuerClassificationEvidenceV1:
    sources = tuple(
        RetainedSourceV1(
            source_id=SEC_CLASSIFICATION_SOURCE,
            uri=source.uri,
            source_version=SEC_CLASSIFICATION_PROFILE,
            terms_reference=SEC_TERMS,
            content=content.get(source.content_hash, media_type=source.media_type),
            captured_at=source.captured_at,
        )
        for source in captured_sources
        if source.source_id == "sec-filing-submission"
        and source.accession_number == request.accession_number
        and source.form == "10-K"
        and source.role is SourceRole.FILING
        and source.http_status == 200
        and source.available_at <= request.valuation_at
    )
    return reproduce_issuer_classification(
        SecSubmissionClassificationProvider(), request=request, sources=sources
    )


def require_statement_issuer_scope(
    classification: IssuerClassificationEvidenceV1,
) -> None:
    if classification.status != "matched" or classification.observation is None:
        raise DataReleaseError(
            "STATEMENT_ISSUER_CLASSIFICATION_UNAVAILABLE",
            "annual statements require the original's point-in-time SEC classification",
        )
    industry = next(
        attribute
        for attribute in classification.observation.attributes
        if attribute.role == "industry_code"
    )
    if industry.scheme != "sec-sic-v1" or not re.fullmatch(r"[0-9]{4}", industry.value):
        raise DataReleaseError(
            "STATEMENT_ISSUER_CLASSIFICATION_UNSUPPORTED",
            "annual statements require the SEC original's four-digit SIC",
        )
    if 6000 <= int(industry.value) <= 6999:
        raise DataReleaseError(
            "STATEMENT_FINANCIAL_ISSUER_UNSUPPORTED",
            "the registered annual statement profile excludes financial SIC industries",
        )
