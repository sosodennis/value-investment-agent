"""Recoverable deterministic parser bodies; ingestion retains admission ownership."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
    parse_filing_offline,
)
from .command_artifacts import EvidenceArtifactStore
from .metadata import IngestionLockLease, PostgresMetadataStore
from .parser_action_evidence import read_parser_action_result
from .parser_action_identity import IncompleteParserClosure, parser_action_input
from .parser_action_contracts import (
    ParserActionInputV1,
    ParserActionResultV1,
    ParserActionUseV1,
)
from .regulatory_validation import (
    require_sec_validation_evidence,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

_LOG = logging.getLogger(__name__)


class ParserActionIndex(Protocol):
    def parser_action_result(self, action_key: str) -> str | None: ...

    def publish_parser_action_result(
        self, action_key: str, artifact_id: str
    ) -> None: ...

    def try_acquire_ingestion_lock(
        self, acquisition_key: str
    ) -> IngestionLockLease | None: ...

    def release_ingestion_lock(self, lease: IngestionLockLease) -> None: ...


class ParserActions:
    """Storage owner verifies every persisted result before issuing its report.

    The mutable PostgreSQL row is only a discoverability index. Immutable result,
    report bytes, dependencies and current metadata are independently checked on
    each hit. An interrupted attempt has no index row and can be retried.
    """

    def __init__(
        self,
        *,
        index: ParserActionIndex,
        artifacts: EvidenceArtifactStore,
    ) -> None:
        self.index, self.artifacts = index, artifacts

    @staticmethod
    def _deadline(deadline_at: datetime) -> None:
        if datetime.now(UTC) >= deadline_at:
            raise ArelleParserError(
                "REQUEST_DEADLINE_EXCEEDED", "parser action deadline expired"
            )

    def _read(
        self,
        request: ParserActionInputV1,
        artifact_id: str,
        profile: ArelleValidationProfileV1,
    ) -> tuple[ArelleParseReportV1, ParserActionResultV1]:
        report, result, _ = read_parser_action_result(
            artifact_id,
            artifacts=self.artifacts,
        )
        if result.request != request or report.validation_profile != profile:
            raise SnapshotError(
                "PARSER_ACTION_EVIDENCE_INVALID", "parser action request differs"
            )
        return report, result

    def parse(
        self,
        path: Path,
        *,
        representation: Literal["normalized", "archive"],
        delivery_revision: str,
        normalization_inputs: tuple[str, ...],
        profile: ArelleValidationProfileV1,
        taxonomy_version: str,
        taxonomy_cache_dir: Path,
        source_content_hash: str,
        deadline_at: datetime,
    ) -> ArelleParseReportV1:
        """Derive the work identity from actual owner-read dependencies."""

        def execute() -> ArelleParseReportV1:
            return parse_filing_offline(
                path,
                profile=profile,
                taxonomy_version=taxonomy_version,
                taxonomy_cache_dir=taxonomy_cache_dir,
                source_content_hash=source_content_hash,
                deadline_at=deadline_at,
            )

        def identity() -> ParserActionInputV1:
            return parser_action_input(
                path,
                representation=representation,
                delivery_revision=delivery_revision,
                normalization_inputs=normalization_inputs,
                profile=profile,
                taxonomy_version=taxonomy_version,
                taxonomy_cache_dir=taxonomy_cache_dir,
                source_content_hash=source_content_hash,
            )

        try:
            request = identity()
        except (IncompleteParserClosure, OSError):
            _LOG.info(
                "sec_parser_action_uncacheable",
                extra={"reason": "incomplete_dependency_closure"},
            )
            return execute()
        return self._perform(
            request=request,
            profile=profile,
            deadline_at=deadline_at,
            execute=execute,
            check_inputs=identity,
        )

    def _perform(
        self,
        *,
        request: ParserActionInputV1,
        profile: ArelleValidationProfileV1,
        deadline_at: datetime,
        execute: Callable[[], ArelleParseReportV1],
        check_inputs: Callable[[], ParserActionInputV1],
    ) -> ArelleParseReportV1:
        self._deadline(deadline_at)
        lease = self.index.try_acquire_ingestion_lock(request.digest)
        while lease is None:
            self._deadline(deadline_at)
            time.sleep(
                min(0.05, max(0, (deadline_at - datetime.now(UTC)).total_seconds()))
            )
            lease = self.index.try_acquire_ingestion_lock(request.digest)
        try:
            artifact_id = self.index.parser_action_result(request.digest)
            report = None
            if artifact_id is not None:
                try:
                    report, result = self._read(request, artifact_id, profile)
                except (SnapshotError, ValueError, OSError):
                    # A cache failure cannot permanently deny a legitimate source.
                    report = None
            reused = report is not None
            _LOG.info(
                "sec_parser_action",
                extra={
                    "action_key": request.digest,
                    "outcome": "hit" if reused else "miss",
                },
            )
            if report is None:
                attempt = f"sec-parser-action-attempt-v1:{request.digest}:{uuid4().hex}"
                self.artifacts.put_with_receipt(
                    attempt,
                    {
                        "request": request,
                        "started_at": datetime.now(UTC),
                    },
                    (request.digest,),
                )
                try:
                    report = execute()
                    require_sec_validation_evidence(report)
                    self._deadline(deadline_at)
                    if check_inputs() != request:
                        raise SnapshotError(
                            "PARSER_ACTION_DEPENDENCY_CHANGED",
                            "parser dependencies changed",
                        )
                    body = canonical_bytes(report.model_dump(mode="json"))
                    body_hash = sha256_digest(report.model_dump(mode="json"))
                    self.artifacts.put_bytes_with_receipt(
                        f"sec-parser-action-report-v1:{body_hash}",
                        body,
                        media_type="application/json",
                    )
                    result = ParserActionResultV1(
                        request=request, report_content_hash=body_hash
                    )
                    self.artifacts.put_with_receipt(
                        result.artifact_id,
                        result,
                        (request.digest, body_hash),
                    )
                    # Validate our own persisted body using the exact same hit path.
                    report, result = self._read(request, result.artifact_id, profile)
                    self._deadline(deadline_at)
                    self.index.publish_parser_action_result(
                        request.digest, result.artifact_id
                    )
                except BaseException as error:
                    self.artifacts.put_with_receipt(
                        attempt + ":failed",
                        {
                            "attempt": attempt,
                            "failed_at": datetime.now(UTC),
                            "error_type": type(error).__name__,
                            "error_code": getattr(
                                error, "code", "PARSER_ACTION_FAILED"
                            ),
                        },
                        (request.digest,),
                    )
                    raise
            else:
                if check_inputs() != request:
                    raise SnapshotError(
                        "PARSER_ACTION_DEPENDENCY_CHANGED",
                        "parser dependencies changed",
                    )
                # Recheck after slow input verification; no TTL grants validity.
                report, result = self._read(request, result.artifact_id, profile)
            self._deadline(deadline_at)
            use = ParserActionUseV1(
                action_key=request.digest,
                result_artifact_id=result.artifact_id,
                report_content_hash=result.report_content_hash,
                delivery_revision=request.delivery_revision,
                used_at=datetime.now(UTC),
                reused=reused,
            )
            self.artifacts.put_with_receipt(
                f"sec-parser-action-use-v1:{sha256_digest(use)}",
                use,
                (request.digest, result.report_content_hash, sha256_digest(result)),
            )
            report, result = self._read(request, result.artifact_id, profile)
            payload = report.model_dump(mode="json")
            payload["validation_evidence"].append(result.evidence_marker())
            bound = ArelleParseReportV1.model_validate(payload)
            self._deadline(deadline_at)
            return bound
        finally:
            self.index.release_ingestion_lock(lease)


def postgres_parser_actions(
    metadata: PostgresMetadataStore,
    artifacts: EvidenceArtifactStore,
) -> ParserActions | None:
    if not metadata.parser_action_reuse_configured:
        return None
    return ParserActions(index=metadata, artifacts=artifacts)
