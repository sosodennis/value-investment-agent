"""Validate shared immutable source evidence within one mapping operation."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import TYPE_CHECKING

from .arelle_parser import ArelleParseReportV1
from .data_releases import DataReleaseError
from .issuer_identity import IdentityResolutionError, validate_original_filing_identity
from .issuer_release_evidence import verify_original_bytes, verify_original_integrity
from .mapping_input_storage import MappingInputReader
from .mapping_input_identity import MappingInputDigests
from .original_issuer import OriginalIssuerEvidenceChecks
from .parser_action_evidence import require_parser_action_evidence
from .parser_action_identity import ParserBuildChecks
from .replay import ArtifactRecordV1
from .serialization import sha256_digest
from .taxonomy_evidence import TaxonomyArchiveChecks, require_original_taxonomy

if TYPE_CHECKING:
    from .automatic_mapping import AutomaticMappingSourceV1


class _MappingArtifactReadScope:
    """Pin checked immutable bytes; recheck metadata on every scoped read."""

    def __init__(
        self, reader: MappingInputReader, *, max_bytes: int, max_entries: int
    ) -> None:
        self.reader = reader
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._size = 0
        self._retained: OrderedDict[str, tuple[ArtifactRecordV1, bytes]] = OrderedDict()

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        return self.reader.get(artifact_id)

    def read(self, artifact_id: str) -> bytes:
        record = self.reader.get(artifact_id)
        previous = self._retained.pop(artifact_id, None)
        if previous is not None:
            if previous[0] == record:
                self._retained[artifact_id] = previous
                return previous[1]
            self._size -= len(previous[1])
        raw = self.reader.read(artifact_id)
        if record.artifact_id != artifact_id or self.reader.get(artifact_id) != record:
            raise DataReleaseError(
                "MAPPING_SOURCE_ARTIFACT_CHANGED",
                "source bytes and metadata must identify one fixed artifact",
            )
        if hashlib.sha256(raw).hexdigest() != record.content_hash:
            # Keep the owning validator's existing corruption error and never reuse it.
            return raw
        if self._max_entries and len(raw) <= self._max_bytes:
            while self._retained and (
                self._size + len(raw) > self._max_bytes
                or len(self._retained) >= self._max_entries
            ):
                _, (_, removed) = self._retained.popitem(last=False)
                self._size -= len(removed)
            self._retained[artifact_id] = record, raw
            self._size += len(raw)
        return raw


class AutomaticMappingEvidenceChecks:
    """Share source checks, never proposal decisions or cross-operation state."""

    def __init__(
        self,
        *,
        max_retained_bytes: int = 256 * 1024 * 1024,
        max_retained_artifacts: int = 128,
        max_retained_report_bytes: int = 64 * 1024 * 1024,
        max_retained_reports: int = 8,
    ) -> None:
        if (
            min(
                max_retained_bytes,
                max_retained_artifacts,
                max_retained_report_bytes,
                max_retained_reports,
            )
            < 0
        ):
            raise ValueError("mapping evidence retention limits must be nonnegative")
        self._checked: dict[str, tuple[str, ...]] = {}
        self.originals = OriginalIssuerEvidenceChecks()
        self.builds = ParserBuildChecks()
        self.taxonomies = TaxonomyArchiveChecks()
        self._max_retained_bytes = max_retained_bytes
        self._max_retained_artifacts = max_retained_artifacts
        self._reader: _MappingArtifactReadScope | None = None
        self._fingerprints: OrderedDict[int, tuple[bytes, str]] = OrderedDict()
        self._fingerprint_bytes = 0
        self._parser_checked: OrderedDict[
            str, tuple[tuple[str, ArtifactRecordV1], ...]
        ] = OrderedDict()
        self._max_parser_checks = max_retained_reports
        self.identities = MappingInputDigests(
            max_bytes=max_retained_report_bytes, max_reports=max_retained_reports
        )

    def report_replay_digest(self, report: ArelleParseReportV1) -> str:
        return self.identities.report_replay_digest(report)

    def require_parser_actions(
        self, request: AutomaticMappingSourceV1, *, artifacts: MappingInputReader
    ) -> None:
        key = sha256_digest(
            (
                self.identities.original_digest(request.original),
                request.source_revision,
                request.evidence_refs,
            )
        )
        previous = self._parser_checked.pop(key, None)
        if previous is None:
            previous = require_parser_action_evidence(
                request.original,
                artifacts=artifacts,
                delivery_revision=request.source_revision,
                evidence_refs=request.evidence_refs,
                original_checks=self.originals,
                build_checks=self.builds,
            )
        for identity, metadata in previous:
            if artifacts.get(identity) != metadata or metadata.status != "valid":
                raise DataReleaseError(
                    "PARSER_ACTION_EVIDENCE_INVALID", "action metadata changed"
                )
        self.builds.verify()
        if self._max_parser_checks:
            while len(self._parser_checked) >= self._max_parser_checks:
                self._parser_checked.popitem(last=False)
            self._parser_checked[key] = previous

    def _content_digest(self, raw: bytes) -> str:
        retained = self._fingerprints.pop(id(raw), None)
        if retained is not None:
            assert retained[0] is raw
            self._fingerprints[id(raw)] = retained
            return retained[1]
        digest = hashlib.sha256(raw).hexdigest()
        if (
            type(raw) is bytes
            and self._max_retained_artifacts
            and len(raw) <= self._max_retained_bytes
        ):
            while self._fingerprints and (
                self._fingerprint_bytes + len(raw) > self._max_retained_bytes
                or len(self._fingerprints) >= self._max_retained_artifacts
            ):
                _, (removed, _) = self._fingerprints.popitem(last=False)
                self._fingerprint_bytes -= len(removed)
            self._fingerprints[id(raw)] = raw, digest
            self._fingerprint_bytes += len(raw)
        return digest

    def reader(self, artifacts: MappingInputReader) -> MappingInputReader:
        if self._reader is None:
            self._reader = _MappingArtifactReadScope(
                artifacts,
                max_bytes=self._max_retained_bytes,
                max_entries=self._max_retained_artifacts,
            )
        elif artifacts is not self._reader and artifacts is not self._reader.reader:
            raise ValueError(
                "one mapping evidence operation requires one artifact store"
            )
        return self._reader

    def assess(
        self, request: AutomaticMappingSourceV1, *, contents: dict[str, bytes]
    ) -> tuple[str, ...]:
        key = sha256_digest(
            (
                request.source_revision,
                request.evaluator_id,
                request.original.model_dump(mode="json", exclude={"report"}),
                self.identities.report_content_digest(request.original.report),
                request.integrity,
                request.evidence_refs,
                request.security_identity,
                tuple(
                    (name, self._content_digest(raw))
                    for name, raw in sorted(contents.items())
                ),
            )
        )
        if key not in self._checked:
            self._checked[key] = _source_reasons(
                request, contents=contents, taxonomy_checks=self.taxonomies
            )
        return self._checked[key]


def _source_reasons(
    request: AutomaticMappingSourceV1,
    *,
    contents: dict[str, bytes],
    taxonomy_checks: TaxonomyArchiveChecks,
) -> tuple[str, ...]:
    original = request.original
    reasons = set(original.issue_codes) if original.status != "matched" else set()
    try:
        for ref in request.evidence_refs:
            if (
                ref.content_hash not in contents
                or hashlib.sha256(contents[ref.content_hash]).hexdigest()
                != ref.content_hash
            ):
                raise DataReleaseError(
                    "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE",
                    "automatic mapping requires its retained evidence bytes",
                )
        require_original_taxonomy(
            original.report.taxonomy_cache_hash or "",
            request.evidence_refs,
            contents,
            archive_checks=taxonomy_checks,
        )
        verify_original_integrity(
            original, request.integrity, parser_version=original.report.parser_version
        )
        verify_original_bytes(request.integrity, contents)
    except DataReleaseError as error:
        reasons.add(error.code)
    if request.security_identity is not None:
        try:
            validate_original_filing_identity(
                request.security_identity,
                cik=original.source.cik,
                ticker=request.security_identity.security_id,
                accepted_at=original.source.available_at,
                facts=original.report.facts,
            )
        except IdentityResolutionError as error:
            reasons.add(error.code)
    return tuple(sorted(reasons))
