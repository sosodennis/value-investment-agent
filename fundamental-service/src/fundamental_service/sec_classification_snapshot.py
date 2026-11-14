"""Read exact complete submissions already retained by SEC acquisition."""

from __future__ import annotations

from hashlib import sha256

from .contracts import SourceRole, SourceSnapshotV1
from .issuer_classification import IssuerClassificationRequestV1
from .sec_classification_source import (
    SEC_CLASSIFICATION_PROFILE,
    SEC_CLASSIFICATION_SOURCE,
)
from .sec_source import SEC_TERMS
from .snapshots import ContentAddressedStore, SnapshotError
from .source_evidence import RetainedSourceV1


class SecSnapshotClassificationSources:
    def __init__(self, content: ContentAddressedStore) -> None:
        self._content = content

    def retained_sources(
        self, request: IssuerClassificationRequestV1, snapshot: SourceSnapshotV1
    ) -> tuple[RetainedSourceV1, ...]:
        records = tuple(
            item
            for item in snapshot.source_records
            if item.source_id == "sec-filing-submission"
            and item.accession_number == request.accession_number
        )
        if len(records) != 1:
            raise SnapshotError(
                "SEC_CLASSIFICATION_SUBMISSION_MISSING"
                if not records
                else "SEC_CLASSIFICATION_SUBMISSION_AMBIGUOUS",
                "classification requires exactly one retained accession-bound submission",
            )
        record = records[0]
        if (
            snapshot.identity.issuer_id != request.issuer_id
            or snapshot.valuation_timestamp != request.valuation_at
            or record.role is not SourceRole.FILING
            or record.http_status != 200
            or record.form != "10-K"
            or record.is_amendment
            or record.available_at > request.valuation_at
            or record.captured_at > snapshot.captured_at
            or record.terms_reference != SEC_TERMS
        ):
            raise SnapshotError(
                "SEC_CLASSIFICATION_SUBMISSION_CONTEXT_MISMATCH",
                "retained submission differs from the original point-in-time context",
            )
        raw = self._content.get(record.content_hash, media_type=record.media_type)
        if sha256(raw).hexdigest() != record.content_hash:
            raise SnapshotError(
                "SOURCE_HASH_MISMATCH", "classification submission bytes changed"
            )
        return (
            RetainedSourceV1(
                source_id=SEC_CLASSIFICATION_SOURCE,
                uri=record.uri,
                source_version=SEC_CLASSIFICATION_PROFILE,
                terms_reference=record.terms_reference,
                content=raw,
                captured_at=record.captured_at,
            ),
        )
