from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Protocol, TypeVar

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel

from .artifact_evidence import read_retained_artifact, require_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .data_releases import (
    ArtifactRefV1,
    DataReleaseActivationCommandV1,
    DataReleaseTrustRootsV1,
    ActiveDataReleaseV1,
)
from .fiscal_admission_history import (
    FiscalActivationObservationV1,
    FiscalAdmissionHistoryReaderPort,
    FiscalAdmissionHistoryPort,
    FiscalHistoryHeadV1,
)
from .fiscal_authority_contracts import (
    FiscalAuthorityGrantV1,
    SignedFiscalAuthorityRecordV1,
)
from .fiscal_candidate_contracts import (
    ClassifiedSourceForCandidateV1,
    FiscalSourceDocumentObservation,
    FiscalSourceUseScopeV1,
    VerifiedClassifiedCandidateSource,
)
from .fiscal_display_contracts import CurrentFiscalDisplay
from .fiscal_read_contracts import (
    FiscalCellV1,
    FiscalDerivedCellV1,
    FiscalDisplayGraphV1,
    FiscalDisplayRowV1,
    FiscalMissingCellV1,
    FiscalQuarterColumnsV1,
    FiscalReadBindingV1,
    FiscalReadRequestV1,
    FiscalReadResultV1,
    FiscalReportedCellV1,
    FiscalSourceInspectionV1,
    FiscalSourceDocumentV1,
    FiscalTtmColumnsV1,
)
from .fiscal_release_contracts import (
    FiscalPublishV1,
    FiscalReleaseCanaryV1,
    FiscalReleaseCandidateReceiptV1,
    FiscalReleaseChecksV1,
    FiscalReleaseEnvelopeV1,
    FiscalReleaseManifestV1,
    FiscalReleaseVerificationV1,
    FiscalStoredVerificationV1,
    fiscal_manifest,
)
from .fiscal_source_closure import FiscalArtifactRead
from .fiscal_statement_policy import fiscal_statement_policy
from .history_recovery_contracts import FiscalHistoryEpochV1
from .metadata import metadata_operation_budget
from .publication_codec import (
    PublicationManifest,
    PublicationVerification,
    verify_fiscal_signature,
    verify_publication_pair,
)
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

_Model = TypeVar("_Model", bound=BaseModel)


class FiscalDisplayReaderPort(Protocol):
    def read_current(
        self,
        decision_ref: ArtifactRefV1,
        candidate_ref: ArtifactRefV1,
        *,
        deadline_at: datetime,
    ) -> CurrentFiscalDisplay: ...


class FiscalPublicationReaderPort(Protocol):
    def get_data_release_manifest(
        self, manifest_digest: str
    ) -> PublicationManifest | None: ...
    def get_data_release_verification(
        self, manifest_digest: str
    ) -> PublicationVerification | None: ...


class FiscalPublicationWriterPort(FiscalPublicationReaderPort, Protocol):
    def publish_data_release_candidate(
        self,
        manifest: PublicationManifest,
        verification: PublicationVerification,
        *,
        fiscal_observation: FiscalActivationObservationV1 | None = None,
    ) -> None: ...
    def compare_and_swap_data_release(
        self,
        command: DataReleaseActivationCommandV1,
        *,
        fiscal_observation: FiscalActivationObservationV1 | None = None,
    ) -> ActiveDataReleaseV1: ...


@dataclass(frozen=True)
class FiscalReleaseSigningJob:
    verifier_id: str
    workflow_identity: str
    verification_suite_digest: str
    source_revision: str
    verification_run_id: str
    authorize: Callable[[FiscalPublishV1, datetime], Ed25519PrivateKey]


@dataclass(frozen=True)
class FiscalReleaseObservation:
    display: CurrentFiscalDisplay
    envelope: FiscalReleaseEnvelopeV1
    manifest: FiscalReleaseManifestV1
    checks: FiscalReleaseChecksV1
    records: tuple[ArtifactRecordV1, ...]
    heads: tuple[FiscalHistoryHeadV1, ...]
    epoch: FiscalHistoryEpochV1
    expires_at: datetime
    configuration: str


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_RELEASE_INVALID", message)


def _reference(record: ArtifactRecordV1, role: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


class FiscalReleaseReader:
    def __init__(
        self,
        *,
        display: FiscalDisplayReaderPort,
        artifacts: EvidenceArtifactStore,
        history: FiscalAdmissionHistoryReaderPort,
        publications: FiscalPublicationReaderPort,
        trust_roots: Callable[[], DataReleaseTrustRootsV1],
        configuration_digest: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        read_operation: Callable[[], AbstractContextManager[None]] = nullcontext,
        seal_read_operation: Callable[[], None] = lambda: None,
        expected_candidate_authority_id: str | None = None,
    ) -> None:
        self.display, self.artifacts, self.history, self.publications = (
            display,
            artifacts,
            history,
            publications,
        )
        self.read_operation, self.seal_read_operation = (
            read_operation,
            seal_read_operation,
        )
        self.expected_candidate_authority_id = expected_candidate_authority_id
        self.trust_roots, self.configuration_digest, self.clock = (
            trust_roots,
            configuration_digest,
            clock,
        )

    def _budget(self, deadline_at: datetime) -> float:
        now = self.clock()
        if (
            now.utcoffset() is None
            or deadline_at.utcoffset() is None
            or now >= deadline_at
        ):
            raise SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED",
                "fiscal release deadline expired",
                retryable=True,
            )
        return (deadline_at - now).total_seconds()

    def _load(
        self,
        reader: FiscalArtifactRead,
        reference: ArtifactRefV1,
        model: type[_Model],
        role: str,
    ) -> _Model:
        raw = read_retained_artifact(reader, reference)
        result = model.model_validate_json(raw)
        if reference.role != role or canonical_bytes(result) != raw:
            raise _invalid("fiscal release retained artifact role or bytes differ")
        return result

    def observe(
        self, approved: FiscalPublishV1, *, deadline_at: datetime
    ) -> FiscalReleaseObservation:
        self._budget(deadline_at)
        generation = self.configuration_digest()
        current = self.display.read_current(
            approved.decision_ref, approved.candidate_ref, deadline_at=deadline_at
        )
        content, projection = current.candidate.content, current.candidate.projection
        if (
            self.expected_candidate_authority_id is not None
            and current.candidate.preparation.authority_id
            != self.expected_candidate_authority_id
        ):
            raise _invalid("fiscal candidate authority differs from installed selector")
        if len({use.scope.display_profile_digest for use in content.source_uses}) != 1:
            raise _invalid("fiscal sources disagree on their display profile")
        envelope = FiscalReleaseEnvelopeV1(
            approved=approved,
            candidate_content_digest=content.content_digest,
            projection_ref=content.projection_ref,
        )
        envelope_ref = ArtifactRefV1(
            role="fiscal-release-envelope-v1",
            artifact_id=envelope.artifact_id,
            content_hash=sha256_digest(envelope),
            media_type="application/json",
        )
        manifest = fiscal_manifest(
            envelope,
            envelope_ref,
            scope=content.scope,
            cutoff_at=content.cutoff_at,
            display_profile_digest=content.source_uses[0].scope.display_profile_digest,
            created_at=current.decision.body.signed_at,
        )
        records = {
            item.artifact_id: item for item in current.candidate.consumed_metadata
        }
        for record in current.consumed_metadata:
            if records.setdefault(record.artifact_id, record) != record:
                raise _invalid("fiscal release observed conflicting metadata")
        heads = {head.stream_id: head for head in current.candidate.history_heads}
        for head in current.history_heads:
            if heads.setdefault(head.stream_id, head) != head:
                raise _invalid("fiscal release observed conflicting history heads")
        values = tuple(sorted(records.values(), key=lambda record: record.artifact_id))
        retained = tuple(
            _reference(record, "fiscal-retained-dependency-v1") for record in values
        )
        checks = FiscalReleaseChecksV1(
            manifest_digest=manifest.manifest_digest,
            candidate_content_digest=content.content_digest,
            raw_source_closure_digest=sha256_digest((content.source_uses, retained)),
            parser_resources_digest=sha256_digest(
                tuple(
                    (
                        use.scope.runtime,
                        use.scope.parser_action_refs,
                        use.scope.raw_report_digest,
                    )
                    for use in content.source_uses
                )
            ),
            mapping_approvals_digest=sha256_digest(content.mapping_refs),
            admission_scope_digest=sha256_digest(
                (current.reference, current.decision, current.candidate.candidate)
            ),
            periods_and_dag_digest=sha256_digest(
                (projection, content.period_set_digest, content.row_lineage_digest)
            ),
            quality_and_policy_digest=sha256_digest(
                (
                    fiscal_statement_policy(),
                    content.projection_policy_digest,
                    content.executable_digest,
                    projection.quality,
                    projection.valuation_eligibility,
                )
            ),
            retained_refs=retained,
        )
        expiries = [
            current.decision.body.command.request.expires_at,
            current.candidate.candidate.body.command.expires_at,
        ]
        for source in current.candidate.source_evidence:
            if isinstance(source, VerifiedClassifiedCandidateSource):
                expiries.extend(source.expires_at)
        reader = FiscalArtifactRead(self.artifacts, partial(self._budget, deadline_at))
        grant_refs = [
            current.candidate.preparation.grant_ref,
            current.decision.body.review.execution.grant_ref,
        ]
        for source in current.candidate.source_evidence:
            if isinstance(source, VerifiedClassifiedCandidateSource):
                grant_refs.extend(activity.grant_ref for activity in source.activities)
        for record in values:
            reader.expect(record.artifact_id, record)
        for reference in grant_refs:
            if reference is not None:
                signed = self._load(
                    reader, reference, SignedFiscalAuthorityRecordV1, reference.role
                )
                if not isinstance(signed.record, FiscalAuthorityGrantV1):
                    raise _invalid("current activity authority is not a grant")
                expiries.append(signed.record.valid_until)
        epoch = self.history.read_epoch(deadline_at=deadline_at)
        return FiscalReleaseObservation(
            current,
            envelope,
            manifest,
            checks,
            values,
            tuple(heads.values()),
            epoch,
            min(expiries),
            generation,
        )

    def finish(
        self,
        observation: FiscalReleaseObservation,
        reader: FiscalArtifactRead,
        *,
        deadline_at: datetime,
    ) -> FiscalActivationObservationV1:
        records = {record.artifact_id: record for record in observation.records}
        for _, record in reader.records:
            if (
                record is not None
                and records.setdefault(record.artifact_id, record) != record
            ):
                raise _invalid("fiscal release evidence metadata conflicted")
        values = tuple(sorted(records.values(), key=lambda item: item.artifact_id))
        reader.check_current()
        self.seal_read_operation()
        observed = self.history.finish_observation(
            values, observation.heads, observation.epoch, deadline_at=deadline_at
        )
        now = self.clock()
        if (
            self.configuration_digest() != observation.configuration
            or now >= observation.expires_at
            or now < observed.observed_through
        ):
            raise _invalid("fiscal release configuration or current permission changed")
        observation.epoch.require_current_activity(now)
        self._budget(deadline_at)
        return FiscalActivationObservationV1(
            values,
            observed.heads,
            observation.epoch,
            observation.expires_at,
            deadline_at,
        )

    def canary(
        self,
        manifest: FiscalReleaseManifestV1,
        signed: FiscalReleaseVerificationV1,
        *,
        deadline_at: datetime,
    ) -> tuple[FiscalReleaseCanaryV1, FiscalReleaseObservation, FiscalArtifactRead]:
        result = self._inspect_canary(manifest, signed, deadline_at=deadline_at)
        self.finish(result[1], result[2], deadline_at=deadline_at)
        return result

    def _inspect_canary(
        self,
        manifest: FiscalReleaseManifestV1,
        signed: FiscalReleaseVerificationV1,
        *,
        deadline_at: datetime,
    ) -> tuple[FiscalReleaseCanaryV1, FiscalReleaseObservation, FiscalArtifactRead]:
        self._budget(deadline_at)
        verify_fiscal_signature(signed, self.trust_roots())
        if signed.manifest_digest != manifest.manifest_digest:
            raise _invalid("fiscal canary signature binds another manifest")
        reader = FiscalArtifactRead(self.artifacts, partial(self._budget, deadline_at))
        signed_id = "fiscal-release-signed-v1:" + manifest.manifest_digest
        signed_record = reader.get(signed_id)
        retained_signed = self._load(
            reader,
            _reference(signed_record, "fiscal-release-signed-v1"),
            FiscalReleaseVerificationV1,
            "fiscal-release-signed-v1",
        )
        marker = reader.get("fiscal-release-signing-v1:" + manifest.manifest_digest)
        if (
            retained_signed != signed
            or reader.read(marker.artifact_id) != signed.signing_bytes()
            or signed_record.dependency_hashes != (signed.checked_ref.content_hash,)
        ):
            raise _invalid("fiscal retained signing outcome or frozen body differs")
        envelope = self._load(
            reader,
            manifest.envelope_ref,
            FiscalReleaseEnvelopeV1,
            "fiscal-release-envelope-v1",
        )
        observed = self.observe(envelope.approved, deadline_at=deadline_at)
        if envelope != observed.envelope or manifest != observed.manifest:
            raise _invalid(
                "fiscal release manifest or envelope differs from owner reconstruction"
            )
        checked = self._load(
            reader,
            signed.checked_ref,
            FiscalReleaseChecksV1,
            "fiscal-release-checks-v1",
        )
        if (
            checked != observed.checks
            or signed.checked_ref.artifact_id != checked.artifact_id
        ):
            raise _invalid("fiscal signed checks differ from actual owner checks")
        return (
            FiscalReleaseCanaryV1(
                manifest_digest=manifest.manifest_digest,
                verification_digest=signed.verification_digest,
                checked_ref=signed.checked_ref,
            ),
            observed,
            reader,
        )

    def pinned(
        self, manifest_digest: str, *, deadline_at: datetime
    ) -> tuple[
        FiscalReleaseManifestV1,
        FiscalStoredVerificationV1,
        FiscalReleaseObservation,
        FiscalArtifactRead,
    ]:
        result = self._inspect_pinned(manifest_digest, deadline_at=deadline_at)
        self.finish(result[2], result[3], deadline_at=deadline_at)
        return result

    def _inspect_pinned(
        self, manifest_digest: str, *, deadline_at: datetime
    ) -> tuple[
        FiscalReleaseManifestV1,
        FiscalStoredVerificationV1,
        FiscalReleaseObservation,
        FiscalArtifactRead,
    ]:
        manifest = self.publications.get_data_release_manifest(manifest_digest)
        verification = self.publications.get_data_release_verification(manifest_digest)
        if not isinstance(manifest, FiscalReleaseManifestV1) or not isinstance(
            verification, FiscalStoredVerificationV1
        ):
            raise _invalid("pinned fiscal publication is unavailable")
        verify_publication_pair(manifest, verification, self.trust_roots())
        expected, observed, reader = self._inspect_canary(
            manifest, verification.signed, deadline_at=deadline_at
        )
        actual = self._load(
            reader,
            verification.canary_ref,
            FiscalReleaseCanaryV1,
            "fiscal-release-canary-v1",
        )
        if (
            actual != expected
            or verification.canary_ref.artifact_id != actual.artifact_id
        ):
            raise _invalid("fiscal canary differs from actual verified checks")
        return manifest, verification, observed, reader

    def activate(
        self,
        command: DataReleaseActivationCommandV1,
        publications: FiscalPublicationWriterPort,
        *,
        deadline_at: datetime,
    ) -> ActiveDataReleaseV1:
        with (
            metadata_operation_budget(
                partial(self._budget, deadline_at),
                lambda: SnapshotError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "fiscal activation deadline expired",
                    retryable=True,
                ),
            ),
            self.read_operation(),
        ):
            manifest, _, observed, reader = self._inspect_pinned(
                command.manifest_digest, deadline_at=deadline_at
            )
            if command.profile_id != manifest.profile_id:
                raise _invalid("fiscal activation profile differs")
            snapshot = self.finish(observed, reader, deadline_at=deadline_at)
            return publications.compare_and_swap_data_release(
                command, fiscal_observation=snapshot
            )

    def _source_document(
        self,
        scope: FiscalSourceUseScopeV1,
        document: FiscalSourceDocumentObservation,
        reader: FiscalArtifactRead,
    ) -> FiscalSourceDocumentV1:
        if (
            document.source_validation_ref != scope.source_validation_ref
            or scope.source_binding_digest != scope.source_validation_ref.content_hash
        ):
            raise _invalid("fiscal source document differs from current source use")
        require_retained_artifact(reader, document.source_validation_ref)
        return FiscalSourceDocumentV1(
            issuer_id=scope.issuer_id,
            accession_number=scope.accession_number,
            primary_document_url=document.primary_document_url,
            primary_document_sha256=document.primary_document_sha256,
            archive_member_sha256=document.archive_member_sha256,
        )

    def read(
        self, request: FiscalReadRequestV1, *, deadline_at: datetime
    ) -> FiscalReadResultV1:
        with (
            metadata_operation_budget(
                partial(self._budget, deadline_at),
                lambda: _invalid("fiscal read deadline expired"),
            ),
            self.read_operation(),
        ):
            manifest, _, observed, reader = self._inspect_pinned(
                request.manifest_digest, deadline_at=deadline_at
            )
            if (request.scope, request.cutoff_at) != (
                manifest.scope,
                manifest.cutoff_at,
            ):
                raise _invalid("fiscal requested scope or cutoff differs")
            projection, content = (
                observed.display.candidate.projection,
                observed.display.candidate.content,
            )
            roots = (
                projection.quarter_nodes
                if request.frequency == "quarter"
                else projection.ttm_nodes
            )
            columns = (
                FiscalQuarterColumnsV1(periods=projection.quarter_periods)
                if request.frequency == "quarter"
                else FiscalTtmColumnsV1(windows=projection.ttm_windows)
            )
            rows = []
            for policy in fiscal_statement_policy().rows:
                cells: list[FiscalCellV1] = []
                for node in roots:
                    if node.row_id != policy.row_id:
                        continue
                    if node.availability == "reported" and node.value is not None:
                        cells.append(
                            FiscalReportedCellV1(
                                node_id=node.node_id,
                                decimal=format(node.value, "f"),
                                source_observation_ids=node.source_observation_ids,
                            )
                        )
                    elif node.availability == "derived" and node.value is not None:
                        cells.append(
                            FiscalDerivedCellV1(
                                node_id=node.node_id, decimal=format(node.value, "f")
                            )
                        )
                    elif (
                        node.availability in {"unavailable", "conflict"}
                        and node.reason_code is not None
                    ):
                        cells.append(
                            FiscalMissingCellV1(
                                kind="conflict"
                                if node.availability == "conflict"
                                else "unavailable",
                                node_id=node.node_id,
                                reason_code=node.reason_code,
                            )
                        )
                    else:
                        raise _invalid(
                            "fiscal display node has incoherent availability"
                        )
                rows.append(FiscalDisplayRowV1(row=policy, cells=tuple(cells)))
            node_map = {node.node_id: node for node in projection.nodes}
            selected = {node.node_id for node in roots}
            pending = list(selected)
            observation_ids: set[str] = set()
            while pending:
                node = node_map[pending.pop()]
                observation_ids.update(
                    (*node.source_observation_ids, *node.verification_observation_ids)
                )
                observation_ids.update(item.observation_id for item in node.candidates)
                for identity in (
                    *tuple(
                        edge.input_id
                        for edge in (*node.input_edges, *node.verification_edges)
                    ),
                    *node.verification_node_ids,
                ):
                    if identity in node_map and identity not in selected:
                        selected.add(identity)
                        pending.append(identity)
                    elif identity not in node_map:
                        observation_ids.add(identity)
            documents = {
                item.source_validation_ref.artifact_id: item
                for item in observed.display.candidate.source_documents
            }
            if len(documents) != len(content.source_uses) or set(documents) != {
                use.scope.source_validation_ref.artifact_id
                for use in content.source_uses
            }:
                raise _invalid("fiscal current source document set differs")
            source_uses = tuple(
                FiscalSourceInspectionV1(
                    source_validation_ref=use.scope.source_validation_ref,
                    source_document=self._source_document(
                        use.scope,
                        documents[use.scope.source_validation_ref.artifact_id],
                        reader,
                    ),
                    validation_kind=use.scope.validation_kind,
                    source_binding_digest=use.scope.source_binding_digest,
                    raw_report_digest=use.scope.raw_report_digest,
                    parser_action_refs=use.scope.parser_action_refs,
                    witness_ref=use.scope.witness_ref,
                    classification_refs=use.classification_refs
                    if isinstance(use, ClassifiedSourceForCandidateV1)
                    else (),
                    mapping_ref=content.mapping_refs[index * 2],
                    mapping_approval_ref=content.mapping_refs[index * 2 + 1],
                )
                for index, use in enumerate(content.source_uses)
            )
            result = FiscalReadResultV1(
                binding=FiscalReadBindingV1(
                    manifest_digest=manifest.manifest_digest,
                    approved=observed.envelope.approved,
                    projection_digest=sha256_digest(projection),
                    scope=manifest.scope,
                    cutoff_at=manifest.cutoff_at,
                    columns=columns,
                    selected_period_set_digest=sha256_digest(columns),
                ),
                rows=tuple(rows),
                evidence=FiscalDisplayGraphV1(
                    nodes=tuple(
                        node for node in projection.nodes if node.node_id in selected
                    ),
                    observations=tuple(
                        item
                        for item in projection.source_observations
                        if item.observation_id in observation_ids
                    ),
                    source_uses=source_uses,
                    reconciliations=tuple(
                        item
                        for item in projection.reconciliations
                        if set(item.input_node_ids).issubset(selected)
                    ),
                    cash_continuities=tuple(
                        item
                        for item in projection.cash_continuities
                        if set(item.input_node_ids).issubset(selected)
                    ),
                ),
            )
            self.finish(observed, reader, deadline_at=deadline_at)
            return result


class FiscalReleaseService:
    def __init__(
        self,
        *,
        reader: FiscalReleaseReader,
        canary: FiscalReleaseReader,
        artifacts: EvidenceArtifactStore,
        history: FiscalAdmissionHistoryPort,
        publications: FiscalPublicationWriterPort,
        signing: FiscalReleaseSigningJob,
    ) -> None:
        (
            self.reader,
            self.canary_reader,
            self.artifacts,
            self.history,
            self.publications,
            self.signing,
        ) = reader, canary, artifacts, history, publications, signing

    def _put(
        self,
        identity: str,
        value: BaseModel,
        dependencies: tuple[str, ...],
        deadline_at: datetime,
    ) -> ArtifactRefV1:
        result = self.artifacts.put_with_receipt(
            identity,
            value,
            dependencies,
            publication_budget=partial(self.reader._budget, deadline_at),
        )
        return _reference(result.artifact, identity.split(":", 1)[0])

    def _checkpoint(
        self, records: tuple[ArtifactRecordV1, ...], deadline_at: datetime
    ) -> None:
        for start in range(0, len(records), 256):
            self.history.checkpoint(
                records[start : start + 256], deadline_at=deadline_at
            )

    def publish(
        self, approved: FiscalPublishV1, *, deadline_at: datetime
    ) -> FiscalReleaseCandidateReceiptV1:
        with metadata_operation_budget(
            partial(self.reader._budget, deadline_at),
            lambda: _invalid("fiscal publication deadline expired"),
        ):
            return self._publish(approved, deadline_at=deadline_at)

    def _publish(
        self, approved: FiscalPublishV1, *, deadline_at: datetime
    ) -> FiscalReleaseCandidateReceiptV1:
        approved = FiscalPublishV1.model_validate_json(canonical_bytes(approved))
        key = self.signing.authorize(approved, deadline_at)
        observed = self.reader.observe(approved, deadline_at=deadline_at)
        envelope_ref = self._put(
            observed.envelope.artifact_id,
            observed.envelope,
            (
                approved.candidate_ref.content_hash,
                approved.decision_ref.content_hash,
                observed.envelope.projection_ref.content_hash,
            ),
            deadline_at,
        )
        if envelope_ref != observed.manifest.envelope_ref:
            raise _invalid("published envelope reference differs")
        checks_ref = self._put(
            observed.checks.artifact_id,
            observed.checks,
            tuple(sorted({ref.content_hash for ref in observed.checks.retained_refs})),
            deadline_at,
        )
        payload = dict(
            protocol="fundamental.fiscal-release-verification.v1",
            manifest_digest=observed.manifest.manifest_digest,
            checked_ref=checks_ref,
            verification_suite_digest=self.signing.verification_suite_digest,
            source_revision=self.signing.source_revision,
            verification_run_id=self.signing.verification_run_id,
            workflow_identity=self.signing.workflow_identity,
            verifier_id=self.signing.verifier_id,
        )
        unsigned = FiscalReleaseVerificationV1.model_validate(
            {
                **payload,
                "verification_digest": sha256_digest(payload),
                "signature": "0" * 128,
            }
        )
        identity = "fiscal-release-signed-v1:" + observed.manifest.manifest_digest
        try:
            record = self.artifacts.get(identity)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            marker = self.artifacts.put_bytes_with_receipt(
                "fiscal-release-signing-v1:" + observed.manifest.manifest_digest,
                unsigned.signing_bytes(),
                media_type="application/json",
                publication_budget=partial(self.reader._budget, deadline_at),
            )
            if not marker.wrote:
                raise SnapshotError(
                    "FISCAL_RELEASE_SIGNING_OUTCOME_UNAVAILABLE",
                    "only the first live workflow may sign its frozen verification",
                )
            self.signing.authorize(approved, deadline_at)
            signed = unsigned.model_copy(
                update={"signature": key.sign(unsigned.signing_bytes()).hex()}
            )
            signed_ref = self._put(
                identity, signed, (checks_ref.content_hash,), deadline_at
            )
            record = self.artifacts.get(signed_ref.artifact_id)
        signed = FiscalReleaseVerificationV1.model_validate_json(
            self.artifacts.read(identity)
        )
        if signed.model_dump(exclude={"signature"}) != unsigned.model_dump(
            exclude={"signature"}
        ):
            raise _invalid("fiscal release signing identity or retained bytes differ")
        self._checkpoint(
            (
                self.artifacts.get(envelope_ref.artifact_id),
                self.artifacts.get(checks_ref.artifact_id),
                record,
                self.artifacts.get(
                    "fiscal-release-signing-v1:" + observed.manifest.manifest_digest
                ),
            ),
            deadline_at,
        )
        report, canary_observed, canary_reader = self.canary_reader.canary(
            observed.manifest, signed, deadline_at=deadline_at
        )
        report_ref = self._put(
            report.artifact_id, report, (checks_ref.content_hash,), deadline_at
        )
        self._checkpoint((self.artifacts.get(report_ref.artifact_id),), deadline_at)
        stored = FiscalStoredVerificationV1(signed=signed, canary_ref=report_ref)
        previous = self.publications.get_data_release_manifest(
            observed.manifest.manifest_digest
        )
        self.canary_reader._load(
            canary_reader, report_ref, FiscalReleaseCanaryV1, "fiscal-release-canary-v1"
        )
        publication_observation = self.canary_reader.finish(
            canary_observed, canary_reader, deadline_at=deadline_at
        )
        self.publications.publish_data_release_candidate(
            observed.manifest, stored, fiscal_observation=publication_observation
        )
        self.reader.pinned(observed.manifest.manifest_digest, deadline_at=deadline_at)
        self.signing.authorize(approved, deadline_at)
        return FiscalReleaseCandidateReceiptV1(
            profile_id=observed.manifest.profile_id,
            release_id=observed.manifest.release_id,
            manifest_digest=observed.manifest.manifest_digest,
            verification_digest=signed.verification_digest,
            envelope_ref=envelope_ref,
            canary_ref=report_ref,
            wrote=previous is None,
        )

    def activate(
        self, command: DataReleaseActivationCommandV1, *, deadline_at: datetime
    ) -> ActiveDataReleaseV1:
        manifest, _, observed, reader = self.reader.pinned(
            command.manifest_digest, deadline_at=deadline_at
        )
        if command.profile_id != manifest.profile_id:
            raise _invalid("fiscal activation profile differs")
        self.signing.authorize(observed.envelope.approved, deadline_at)
        snapshot = self.reader.finish(observed, reader, deadline_at=deadline_at)
        with metadata_operation_budget(
            partial(self.reader._budget, deadline_at),
            lambda: _invalid("fiscal activation deadline expired"),
        ):
            return self.publications.compare_and_swap_data_release(
                command, fiscal_observation=snapshot
            )
