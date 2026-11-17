"""Operation-local canonical identities for mappings sharing immutable reports."""

from __future__ import annotations

import hashlib
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from .arelle_parser import ArelleParseReportV1, ParsedXbrlFactV1, fact_semantic_digest
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import canonical_bytes, sha256_digest


def _object_parts(
    fields: dict[str, Any], name: str, embedded: tuple[bytes, ...]
) -> tuple[bytes, ...]:
    """Insert owner-produced canonical JSON without expanding it again."""
    parts = [b"{"]
    for index, key in enumerate(sorted((*fields, name))):
        if index:
            parts.append(b",")
        parts.extend((canonical_bytes(key), b":"))
        parts.extend(embedded if key == name else (canonical_bytes(fields[key]),))
    parts.append(b"}")
    return tuple(parts)


def _digest_parts(parts: tuple[bytes, ...]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


@dataclass
class _ReportIdentity:
    report: ArelleParseReportV1
    canonical: bytes
    content_digest: str
    replay_digest: str | None = None
    semantic_digest: str | None = None
    facts: Mapping[str, ParsedXbrlFactV1] | None = None
    index_bytes: int = 0

    @property
    def retained_bytes(self) -> int:
        return len(self.canonical) + self.index_bytes

    identities: OrderedDict[tuple[str, str], str] = field(default_factory=OrderedDict)

    def remember(self, key: tuple[str, str], digest: str) -> str:
        self.identities[key] = digest
        self.identities.move_to_end(key)
        if len(self.identities) > 256:
            self.identities.popitem(last=False)
        return digest


class MappingInputDigests:
    """Preserve fundamental-json-v1 digests; retain no cross-operation claims.

    Only exact frozen report instances share canonical bytes. Original headers
    and every request field still participate in identity. These fingerprints
    authorize no content, metadata, accounting rule or signature on their own.
    """

    def __init__(self, *, max_bytes: int = 64 * 1024 * 1024, max_reports: int = 8):
        if min(max_bytes, max_reports) < 0:
            raise ValueError("report identity retention limits must be nonnegative")
        self._max_bytes = max_bytes
        self._max_reports = max_reports
        self._size = 0
        self._reports: OrderedDict[int, _ReportIdentity] = OrderedDict()

    def _report(self, report: ArelleParseReportV1) -> _ReportIdentity:
        retained = self._reports.pop(id(report), None)
        if retained is not None:
            assert retained.report is report
            self._reports[id(report)] = retained
            return retained
        raw = canonical_bytes(report.model_dump(mode="json"))
        result = _ReportIdentity(report, raw, hashlib.sha256(raw).hexdigest())
        if self._max_reports and len(raw) <= self._max_bytes:
            while self._reports and (
                self._size + len(raw) > self._max_bytes
                or len(self._reports) >= self._max_reports
            ):
                _, removed = self._reports.popitem(last=False)
                self._size -= removed.retained_bytes
            self._reports[id(report)] = result
            self._size += len(raw)
        return result

    def report_bytes(self, report: ArelleParseReportV1) -> bytes:
        return self._report(report).canonical

    def report_content_digest(self, report: ArelleParseReportV1) -> str:
        return self._report(report).content_digest

    def report_replay_digest(self, report: ArelleParseReportV1) -> str:
        retained = self._report(report)
        if retained.replay_digest is None:
            retained.replay_digest = report.replay_digest()
        return retained.replay_digest

    def report_fact_digest(self, report: ArelleParseReportV1) -> str:
        retained = self._report(report)
        if retained.semantic_digest is None:
            retained.semantic_digest = fact_semantic_digest(report)
        return retained.semantic_digest

    def report_facts(
        self, report: ArelleParseReportV1
    ) -> Mapping[str, ParsedXbrlFactV1]:
        """Reuse the existing exact-observation index; retain all report facts."""
        retained = self._report(report)
        if retained.facts is not None:
            return retained.facts
        facts = {sha256_digest(fact): fact for fact in report.facts}
        immutable = MappingProxyType(facts)
        if self._reports.get(id(report)) is retained:
            retained.facts = immutable
            retained.index_bytes = sys.getsizeof(facts) + sum(
                sys.getsizeof(key) for key in facts
            )
            self._size += retained.index_bytes
            while self._reports and self._size > self._max_bytes:
                _, removed = self._reports.popitem(last=False)
                self._size -= removed.retained_bytes
        return immutable

    @staticmethod
    def _original(
        original: OriginalIssuerEvidenceV1, report: _ReportIdentity
    ) -> tuple[tuple[bytes, ...], str]:
        fields = original.model_dump(mode="python", exclude={"report"})
        key = ("original", sha256_digest(fields))
        parts = _object_parts(fields, "report", (report.canonical,))
        digest = report.identities.get(key)
        if digest is None:
            digest = report.remember(key, _digest_parts(parts))
        return parts, digest

    def original_digest(self, original: OriginalIssuerEvidenceV1) -> str:
        return self._original(original, self._report(original.report))[1]

    def input_digest(self, request: BaseModel) -> str:
        original = getattr(request, "original", None)
        if not isinstance(original, OriginalIssuerEvidenceV1):
            raise ValueError("mapping identity requires an original issuer report")
        report = self._report(original.report)
        parts, original_digest = self._original(original, report)
        fields = request.model_dump(mode="python", exclude={"original"})
        key = ("input", sha256_digest((fields, original_digest)))
        digest = report.identities.get(key)
        if digest is None:
            digest = report.remember(
                key, _digest_parts(_object_parts(fields, "original", parts))
            )
        return digest
