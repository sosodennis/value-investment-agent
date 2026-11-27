from __future__ import annotations

import os
import hashlib
from asyncio import current_task
from threading import get_ident
from contextvars import ContextVar

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol
from dataclasses import dataclass

from pydantic import AwareDatetime, ConfigDict, Field

from .artifact_evidence import read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_candidate_contracts import (
    FiscalSourceDocumentObservation,
    ClassifiedSourceForCandidateV1,
    FiscalCandidateClassificationBindingV1,
    FiscalCandidateSourceUseV1,
    FiscalSourceUseScopeV1,
    FiscalCandidateContentV2,
    FiscalCandidateSourceReplayRefV1,
    FiscalOwnerCorrectnessV1,
    FiscalPreparedCorrectnessV1,
    CorrectnessOwner,
    _TrustedCandidateCorrectness,
    FiscalPrepareCandidateCommandV2,
    VerifiedClassifiedCandidateSource,
    VerifiedRawCandidateSource,
    VerifiedFiscalCandidateSource,
    VerifiedRawSourceForCandidateV1,
)
from .fiscal_discovery import FiscalDiscovery, FiscalDiscoveryEvidenceV1
from .fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalArtifactReadSet,
    FiscalSourceContentReadSet,
    FiscalSourceClosure,
    FiscalSourceContentRead,
    FiscalSourceRead,
    bound_fiscal_closure_value,
)
from .fiscal_statement_contracts import (
    FiscalBasisFilingV1,
    FiscalBasisObservationV1,
    FiscalComparativePairV1,
    FiscalDurationPeriodV1,
    FiscalObservationV1,
    FiscalPeriodTargetV1,
    FiscalProjectionInputV1,
    FiscalProjectionResultV1,
    FiscalRevisionBasisProofV1,
    FiscalTtmWindowV1,
    ReportedQuarterV1,
)
from .fiscal_statement_mapping import (
    FiscalMappingApprovalOwner,
    FiscalMappingVerifier,
    FiscalStatementMappingBatchV1,
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
    fiscal_projection_executable_digest,
    map_fiscal_primary_source,
)
from .fiscal_statement_policy import fiscal_statement_policy
from .fiscal_parser_evidence import fiscal_source_closure_contract_digest
from .fiscal_statement_projection import project_fiscal_statements
from .fiscal_statement_registry import (
    Digest,
    FiscalFourthQuarterBoundaryV1,
    FiscalQuarterReviewV1,
    FiscalReviewedCoverageV1,
    FiscalRowBasisPlanV1,
    fiscal_primary_scopes,
    fiscal_statement_registry,
    selected_fiscal_coverage,
)
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalOriginalValidationRequestV1,
    FiscalValidationCompleteRefusedV1,
    FiscalValidationIncompleteV1,
    FiscalValidationPinV1,
    FiscalRetainedInputBindingV1,
    ResolvedFiscalValidationRequestV1,
)
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError

if TYPE_CHECKING:
    from .fiscal_candidate_preparation import (
        FiscalCandidatePreparation,
        FiscalCandidateOperation,
        CurrentFiscalCandidate,
    )
from .statement_contracts import StatementScopeV1


class FiscalClassifiedSourceReadPort(Protocol):
    def current(self) -> VerifiedClassifiedCandidateSource: ...

    @property
    def correctness_inputs(
        self,
    ) -> tuple[tuple[CorrectnessOwner, ArtifactRefV1, tuple[object, ...]], ...]: ...

    @property
    def artifact_readset(self) -> FiscalArtifactReadSet: ...

    @property
    def content_readsets(self) -> tuple[FiscalSourceContentReadSet, ...]: ...


class FiscalCandidateClassificationPort(Protocol):
    def _open_current_source(
        self,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        binding: FiscalRetainedInputBindingV1,
        *,
        deadline_at: datetime,
    ) -> AbstractContextManager[FiscalClassifiedSourceReadPort]: ...

    def open_candidate_source(
        self,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        *,
        deadline_at: datetime,
    ) -> AbstractContextManager[FiscalClassifiedSourceReadPort]: ...


class FiscalCoverageBasisEvidenceV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-reconstructed-basis-review.v1"] = (
        "fundamental.fiscal-reconstructed-basis-review.v1"
    )
    coverage: FiscalReviewedCoverageV1
    observations: tuple[FiscalBasisObservationV1, ...]
    filings: tuple[FiscalBasisFilingV1, ...]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    cutoff_at: AwareDatetime
    source_set_digest: Digest
    mapping_refs: tuple[ArtifactRefV1, ...]


@dataclass(frozen=True)
class FiscalCandidateMaterialization:
    content: FiscalCandidateContentV2
    projection: FiscalProjectionResultV1
    consumed_metadata: tuple[ArtifactRecordV1, ...]
    source_evidence: tuple[VerifiedFiscalCandidateSource, ...]
    source_documents: tuple[FiscalSourceDocumentObservation, ...]
    correctness: FiscalPreparedCorrectnessV1
    artifact_readset: FiscalArtifactReadSet
    content_readsets: tuple[FiscalSourceContentReadSet, ...]


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_PROJECTION_SOURCE_INVALID", message)


@dataclass(frozen=True)
class _RawMaterializedSource:
    source: FiscalSourceRead
    proof: VerifiedRawCandidateSource


@dataclass(frozen=True)
class _ClassifiedMaterializedSource:
    source: FiscalSourceRead
    admission: FiscalClassifiedSourceReadPort
    proof: VerifiedClassifiedCandidateSource


_MATERIALIZATION_READS: ContextVar[tuple[object, ...]] = ContextVar(
    "fiscal_materialization_reads", default=()
)


def _materialization_actor() -> tuple[object, ...]:
    try:
        task: object | None = current_task()
    except RuntimeError:
        task = None
    return (
        os.getpid(),
        get_ident(),
        task,
        os.getuid(),
        os.geteuid(),
        os.getgid(),
        os.getegid(),
        tuple(sorted(os.getgroups())),
    )


class _MaterializationRead:
    def __init__(self, owner: FiscalProjectionBuilder, deadline_at: datetime) -> None:
        self.owner, self.deadline_at = owner, deadline_at
        self.reader = FiscalArtifactRead(
            owner.read_artifacts, partial(owner._budget, deadline_at)
        )
        self.content = FiscalSourceContentRead(
            owner.content, partial(owner._budget, deadline_at)
        )
        self.children = ExitStack()
        self.sources: list[_RawMaterializedSource | _ClassifiedMaterializedSource] = []
        self.approvals: list[tuple[FiscalStatementMappingBatchV1, ArtifactRefV1]] = []
        self.image: FiscalCandidateMaterialization | None = None
        self._owners = (
            owner.discovery,
            owner.sources,
            owner.artifacts,
            owner.read_artifacts,
            owner.mapping_publications,
            owner.content,
            owner.mapping_approvals,
            owner.classifications,
            owner.clock,
        )
        self._configuration = self._configured()
        self._actor = _materialization_actor()
        self._closed = False
        self.discovery_inputs: tuple[object, ...] = ()
        self.discovery_content_readsets: tuple[FiscalSourceContentReadSet, ...] = ()
        self.mapping_reads: list[FiscalArtifactRead] = []
        self.mapping_consumption: list[tuple[object, ...]] = []
        self.basis_read = self.reader.for_consumer()

    def _read_discovery(self, reference: ArtifactRefV1) -> FiscalDiscoveryEvidenceV1:
        observed = self.owner.discovery.read_with_inputs(
            reference.artifact_id, deadline_at=self.deadline_at
        )
        if self.discovery_inputs and self.discovery_inputs != observed.input_footprint:
            raise _invalid("discovery input consumption changed")
        self.discovery_inputs = observed.input_footprint
        self.reader.enroll(observed.artifact_readset)
        self.discovery_content_readsets = observed.content_readsets
        for identity, record in observed.records:
            self.reader.expect(identity, record)
        return observed.evidence

    def _configured(self) -> bytes:
        return canonical_bytes(
            (
                self.owner.pin,
                fiscal_statement_registry(),
                fiscal_mapping_policy_digest(),
                fiscal_display_profile_digest(),
                fiscal_statement_policy().digest,
                fiscal_projection_executable_digest(),
            )
        )

    def close(self) -> None:
        self._closed = True
        self.children.close()
        self.sources.clear()
        self.approvals.clear()
        self.image = None

    def _content_readsets(self) -> tuple[FiscalSourceContentReadSet, ...]:
        values = [self.content.readset, *self.discovery_content_readsets]
        for slot in self.sources:
            values.extend(slot.source.content_readsets)
            if isinstance(slot, _ClassifiedMaterializedSource):
                values.extend(slot.admission.content_readsets)
        return tuple(values)

    def current(self) -> FiscalCandidateMaterialization:
        if self._closed or self.image is None:
            raise _invalid("fiscal materialization observation is closed")
        if (
            self._actor != _materialization_actor()
            or self not in _MATERIALIZATION_READS.get()
        ):
            self.close()
            raise _invalid("materialization observation belongs to another execution")
        try:
            owner = self.owner
            owner._budget(self.deadline_at)
            if (
                self._owners
                != (
                    owner.discovery,
                    owner.sources,
                    owner.artifacts,
                    owner.read_artifacts,
                    owner.mapping_publications,
                    owner.content,
                    owner.mapping_approvals,
                    owner.classifications,
                    owner.clock,
                )
                or self._configuration != self._configured()
            ):
                raise _invalid(
                    "fiscal materialization configured owner or policy changed"
                )
            discovery_ref = self.image.content.discovery_ref
            discovery = self._read_discovery(discovery_ref)
            if read_retained_artifact(self.reader, discovery_ref) != canonical_bytes(
                discovery
            ):
                raise _invalid("fiscal discovery changed during materialization")
            proofs: list[VerifiedFiscalCandidateSource] = []
            for slot in self.sources:
                slot.source.check_current()
                if (
                    sha256_digest(slot.source.evidence.model_dump(mode="json"))
                    != slot.proof.source_use.scope.source_validation_ref.content_hash
                ):
                    raise _invalid("candidate source changed before completion")
                self.reader.enroll(slot.source.artifact_readset)
                if isinstance(slot, _ClassifiedMaterializedSource):
                    proof = slot.admission.current()
                    if proof != slot.proof:
                        raise _invalid(
                            "candidate classification proof changed before completion"
                        )
                    for record in proof.consumed_metadata:
                        self.reader.expect(record.artifact_id, record)
                    self.reader.enroll(slot.admission.artifact_readset)
                    proofs.append(proof)
                else:
                    proofs.append(slot.proof)
            if owner.mapping_approvals is None:
                raise _invalid("candidate mapping authority disappeared")
            for batch, approval in self.approvals:
                owner.mapping_approvals.verify(
                    batch, approval, deadline_at=self.deadline_at
                )
            self.content.check_current()
            self.reader.check_bodies()
            if (
                self.owner._correctness(self.image.content, self)
                != self.image.correctness
            ):
                raise _invalid(
                    "current owner consumption differs from its prepared correctness"
                )
            owner._budget(self.deadline_at)
            return deepcopy(
                FiscalCandidateMaterialization(
                    self.image.content,
                    self.image.projection,
                    tuple(
                        record
                        for _, record in self.reader.records
                        if record is not None
                    ),
                    tuple(proofs),
                    self.image.source_documents,
                    self.image.correctness,
                    self.reader.readset,
                    self._content_readsets(),
                )
            )
        except BaseException:
            self.close()
            raise


class _CurrentMaterializationRead(_MaterializationRead):
    def _read_discovery(self, reference: ArtifactRefV1) -> FiscalDiscoveryEvidenceV1:
        observed = self.owner.discovery.read_current_inputs(
            reference.artifact_id, deadline_at=self.deadline_at
        )
        if self.discovery_inputs and self.discovery_inputs != observed.input_footprint:
            raise _invalid("current discovery typed closure changed")
        self.discovery_inputs = observed.input_footprint
        self.reader.enroll(observed.artifact_readset)
        self.discovery_content_readsets = observed.content_readsets
        for identity, record in observed.records:
            self.reader.expect(identity, record)
        return observed.evidence


class FiscalProjectionBuilder:
    def __init__(
        self,
        *,
        discovery: FiscalDiscovery,
        sources: FiscalSourceClosure,
        artifacts: EvidenceArtifactStore,
        read_artifacts: EvidenceArtifactStore,
        content: ContentAddressedStore,
        pin: FiscalValidationPinV1,
        mapping_approvals: FiscalMappingVerifier | None,
        mapping_publications: FiscalMappingApprovalOwner | None = None,
        preparation: FiscalCandidatePreparation | None = None,
        classifications: FiscalCandidateClassificationPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.discovery, self.sources, self.artifacts, self.content = (
            discovery,
            sources,
            artifacts,
            content,
        )
        self.read_artifacts = read_artifacts
        self.mapping_publications = mapping_publications
        self.pin, self.mapping_approvals = pin, mapping_approvals
        self.preparation, self.classifications, self.clock = (
            preparation,
            classifications,
            clock,
        )

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal projection preparation deadline expired",
            retryable=True,
        )

    def _budget(self, deadline_at: datetime) -> float:
        now = self.clock()
        if (
            now.utcoffset() is None
            or deadline_at.utcoffset() is None
            or deadline_at <= now
        ):
            raise self._expired()
        return (deadline_at - now).total_seconds()

    @staticmethod
    def closure_contract_digest() -> str:
        from pathlib import Path

        root = Path(__file__).parent
        return sha256_digest(
            (
                "fundamental.fiscal-current-closure.v2",
                fiscal_source_closure_contract_digest(),
                tuple(
                    (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
                    for name in (
                        "fiscal_candidate_contracts.py",
                        "fiscal_admission_authority.py",
                        "fiscal_projection_builder.py",
                        "fiscal_discovery.py",
                        "fiscal_classification_source.py",
                        "fiscal_focus_witness.py",
                        "fiscal_source_classification.py",
                        "fiscal_source_preparation.py",
                        "fiscal_source_accounting_policy_contracts.py",
                        "fiscal_statement_mapping.py",
                        "fiscal_statement_contracts.py",
                        "fiscal_statement_registry.py",
                        "fiscal_statement_projection.py",
                        "fiscal_statement_policy.py",
                    )
                ),
            )
        )

    def _correctness(
        self, content: FiscalCandidateContentV2, read: _MaterializationRead
    ) -> FiscalPreparedCorrectnessV1:
        contract = self.closure_contract_digest()
        owners = []

        def add(
            owner: CorrectnessOwner,
            path: str,
            root: ArtifactRefV1,
            policy: str,
            footprint: object,
        ) -> None:
            bound_fiscal_closure_value((owner, path), footprint)
            owners.append(
                FiscalOwnerCorrectnessV1(
                    owner=owner,
                    use_path=path,
                    root_ref=root,
                    contract_digest=contract,
                    executable_digest=contract,
                    policy_digest=policy,
                    input_footprint_digest=sha256_digest(footprint),
                )
            )

        add(
            "discovery",
            "discovery",
            content.discovery_ref,
            sha256_digest(fiscal_statement_registry()),
            read.discovery_inputs,
        )
        for index, (use, replay, slot, mapping_read) in enumerate(
            zip(
                content.source_uses,
                content.source_replay_refs,
                read.sources,
                read.mapping_reads,
                strict=True,
            )
        ):
            path = "source/" + str(index)
            add(
                "source_ingestion",
                path,
                use.scope.source_validation_ref,
                fiscal_source_closure_contract_digest(),
                slot.source.input_footprint,
            )
            add(
                "parser_binding",
                path,
                replay.input_binding_ref,
                fiscal_source_closure_contract_digest(),
                slot.source.retained_input_binding(use.scope.source_validation_ref),
            )
            add(
                "mapping",
                path,
                content.mapping_refs[2 * index],
                fiscal_mapping_policy_digest(),
                (read.mapping_consumption[index], mapping_read.input_footprint),
            )
            if isinstance(slot, _ClassifiedMaterializedSource):
                for owner, root, footprint in slot.admission.correctness_inputs:
                    add(owner, path, root, fiscal_mapping_policy_digest(), footprint)
        add(
            "basis_projection",
            "projection",
            content.projection_input_ref,
            fiscal_statement_policy().digest,
            read.basis_read.input_footprint,
        )
        return FiscalPreparedCorrectnessV1(
            candidate_content_digest=content.content_digest,
            closure_contract_digest=contract,
            owners=tuple(owners),
        )

    @contextmanager
    def _open_current_materialization(
        self, trusted: _TrustedCandidateCorrectness, *, deadline_at: datetime
    ) -> Iterator[_CurrentMaterializationRead]:
        with self._derive_current_materialization(
            trusted.candidate.body.content, deadline_at=deadline_at
        ) as read:
            if (
                read.image is None
                or read.image.correctness != trusted.candidate.body.correctness
            ):
                raise _invalid("current owner closure differs from trusted preparation")
            yield read

    @contextmanager
    def _derive_current_materialization(
        self, content: FiscalCandidateContentV2, *, deadline_at: datetime
    ) -> Iterator[_CurrentMaterializationRead]:
        read = _CurrentMaterializationRead(self, deadline_at)
        token = _MATERIALIZATION_READS.set((*_MATERIALIZATION_READS.get(), read))
        try:
            self._current_materialization(content, read)
            yield read
        finally:
            read.close()
            _MATERIALIZATION_READS.reset(token)

    def _current_materialization(
        self, content: FiscalCandidateContentV2, read: _CurrentMaterializationRead
    ) -> None:
        deadline_at, reader = read.deadline_at, read.reader
        if (
            content.materialization != self.pin
            or content.executable_digest != fiscal_projection_executable_digest()
            or content.projection_policy_digest != fiscal_statement_policy().digest
            or self.mapping_approvals is None
        ):
            raise _invalid("prepared materialization version or current policy differs")
        discovery = read._read_discovery(content.discovery_ref)
        if read_retained_artifact(reader, content.discovery_ref) != canonical_bytes(
            discovery
        ):
            raise _invalid("prepared discovery root differs")
        coverage = selected_fiscal_coverage(discovery)
        if (
            tuple(item.scope.accession_number for item in content.source_uses)
            != coverage.source_accessions
        ):
            raise _invalid("prepared source uses differ from reviewed coverage")
        documents = []
        proofs = []
        for index, (use, replay) in enumerate(
            zip(content.source_uses, content.source_replay_refs, strict=True)
        ):
            raw = read_retained_artifact(reader, replay.input_binding_ref)
            binding = FiscalRetainedInputBindingV1.model_validate_json(raw)
            if (
                canonical_bytes(binding) != raw
                or binding.source_validation_ref != use.scope.source_validation_ref
            ):
                raise _invalid("prepared source replay binding differs")
            source = self.sources._observe_current(
                use.scope.source_validation_ref.artifact_id,
                binding,
                deadline_at=deadline_at,
            )
            evidence = source.evidence
            if (
                isinstance(evidence.outcome, FiscalValidationIncompleteV1)
                or evidence.outcome.runtime != use.scope.runtime
            ):
                raise _invalid("prepared source runtime differs")
            reader.enroll(source.artifact_readset)
            proof: VerifiedFiscalCandidateSource
            if isinstance(use, ClassifiedSourceForCandidateV1):
                if self.classifications is None:
                    raise _invalid("current classification owner is unavailable")
                admission = read.children.enter_context(
                    self.classifications._open_current_source(
                        use.scope,
                        use.classification_refs,
                        binding,
                        deadline_at=deadline_at,
                    )
                )
                proof = admission.current()
                if proof.source_use != use:
                    raise _invalid(
                        "current classification changes the prepared source use"
                    )
                read.sources.append(
                    _ClassifiedMaterializedSource(source, admission, proof)
                )
                for record in proof.consumed_metadata:
                    reader.expect(record.artifact_id, record)
                reader.enroll(admission.artifact_readset)
            else:
                proof = VerifiedRawCandidateSource(
                    use,
                    evidence.outcome.action_refs,
                    tuple(record for _, record in source.records if record is not None),
                )
                read.sources.append(_RawMaterializedSource(source, proof))
            proofs.append(proof)
            mapping = reader.for_consumer()
            batch_ref, approval_ref = content.mapping_refs[2 * index : 2 * index + 2]
            batch_raw = read_retained_artifact(mapping, batch_ref)
            batch = FiscalStatementMappingBatchV1.model_validate_json(batch_raw)
            if (
                canonical_bytes(batch) != batch_raw
                or batch.source_validation_ref != use.scope.source_validation_ref
                or batch.observations != use.scope.permitted_inputs
                or batch.source_binding_digest != use.scope.source_binding_digest
                or batch.policy_digest != fiscal_mapping_policy_digest()
            ):
                raise _invalid("prepared mapping differs from its exact source use")
            self._retain(
                batch,
                "fiscal-statement-mapping-v1",
                (
                    batch.source_validation_ref.content_hash,
                    batch.primary_scope_digest,
                    batch.policy_digest,
                ),
                mapping,
                publish=False,
                deadline_at=deadline_at,
            )
            self.mapping_approvals.verify(batch, approval_ref, deadline_at=deadline_at)
            read_retained_artifact(mapping, approval_ref)
            for disclosure in batch.disclosures:
                self._retain(
                    disclosure,
                    "fiscal-accounting-disclosure-v1",
                    (
                        batch.source_validation_ref.content_hash,
                        disclosure.primary_member_sha256,
                    ),
                    mapping,
                    publish=False,
                    deadline_at=deadline_at,
                )
            read.mapping_reads.append(mapping)
            read.approvals.append((batch, approval_ref))
            archive_receipt = next(
                item
                for item in evidence.outcome.responses
                if item.uri == evidence.outcome.integrity.archive_uri
            )
            archive = read.content.get(
                archive_receipt.content_hash, media_type=archive_receipt.media_type
            )
            reviewed = next(
                item
                for item in fiscal_primary_scopes(fiscal_statement_registry())
                if item.accession_number == use.scope.accession_number
            )
            read.mapping_consumption.append(
                (
                    use.scope.source_validation_ref,
                    sha256_digest(evidence.model_dump(mode="json")),
                    hashlib.sha256(archive).hexdigest(),
                    len(archive),
                    reviewed,
                    tuple(item.period for item in coverage.quarters),
                    content.scope.security_id,
                    fiscal_mapping_policy_digest(),
                )
            )
            documents.append(
                FiscalSourceDocumentObservation(
                    use.scope.source_validation_ref,
                    evidence.outcome.claim.source.uri,
                    evidence.outcome.integrity.raw_content_hash,
                    evidence.outcome.integrity.archive_member_hash,
                )
            )
        basis_raw = read_retained_artifact(read.basis_read, content.basis_review_ref)
        basis = FiscalCoverageBasisEvidenceV1.model_validate_json(basis_raw)
        if (
            canonical_bytes(basis) != basis_raw
            or basis.coverage != coverage
            or basis.mapping_refs != content.mapping_refs
            or basis.source_set_digest != content.source_set_digest
            or basis.cutoff_at != content.cutoff_at
            or basis.source_revision != self.pin.declared_source_revision
        ):
            raise _invalid("prepared basis review root differs")
        self._retain(
            basis,
            "fiscal-basis-review-v1",
            tuple(ref.content_hash for ref in basis.mapping_refs)
            + tuple(
                ref.content_hash
                for filing in basis.filings
                for ref in filing.disclosure_refs
            ),
            read.basis_read,
            publish=False,
            deadline_at=deadline_at,
        )
        projection_raw = read_retained_artifact(read.basis_read, content.projection_ref)
        projection = FiscalProjectionResultV1.model_validate_json(projection_raw)
        input_raw = read_retained_artifact(
            read.basis_read, content.projection_input_ref
        )
        projection_input = FiscalProjectionInputV1.model_validate_json(input_raw)
        if (
            canonical_bytes(projection_input) != input_raw
            or projection_input.observations
            != tuple(
                item
                for use in content.source_uses
                for item in use.scope.permitted_inputs
            )
            or projection_input.scope != content.scope
            or projection_input.cutoff_at != content.cutoff_at
            or projection_input.source_binding_digest != content.source_set_digest
            or projection_input.source_revision != self.pin.declared_source_revision
            or projection_input.executable_digest != content.executable_digest
            or projection_input.quarter_targets != projection.quarter_periods
            or projection_input.ttm_windows != projection.ttm_windows
            or any(
                proof.review_evidence_ref != content.basis_review_ref
                for proof in projection_input.basis_proofs
            )
        ):
            raise _invalid(
                "prepared full projection input differs from typed source, period or basis roots"
            )
        self._retain(
            projection_input,
            "fiscal-statement-projection-input-v1",
            tuple(ref.content_hash for ref in content.mapping_refs)
            + (content.basis_review_ref.content_hash, content.source_set_digest),
            read.basis_read,
            publish=False,
            deadline_at=deadline_at,
        )
        if (
            canonical_bytes(projection) != projection_raw
            or projection.executable_digest != content.executable_digest
            or sha256_digest((projection.quarter_periods, projection.ttm_windows))
            != content.period_set_digest
            or sha256_digest(
                tuple(
                    (item.node_id, item.input_edges, item.verification_edges)
                    for item in projection.nodes
                )
            )
            != content.row_lineage_digest
            or projection.source_observations
            != tuple(
                item
                for use in content.source_uses
                for item in use.scope.permitted_inputs
            )
        ):
            raise _invalid("prepared projection or exact source lineage differs")
        self._retain(
            projection,
            "fiscal-statement-projection-v1",
            tuple(ref.content_hash for ref in content.mapping_refs)
            + tuple(
                proof.review_evidence_ref.content_hash
                for proof in projection_input.basis_proofs
            ),
            read.basis_read,
            publish=False,
            deadline_at=deadline_at,
        )
        correctness = self._correctness(content, read)
        read.image = FiscalCandidateMaterialization(
            content,
            projection,
            tuple(record for _, record in reader.records if record is not None),
            tuple(proofs),
            tuple(documents),
            correctness,
            reader.readset,
            read._content_readsets(),
        )

    def _retain(
        self,
        value: object,
        role: str,
        dependencies: tuple[str, ...],
        reader: FiscalArtifactRead,
        *,
        publish: bool,
        deadline_at: datetime,
    ) -> ArtifactRefV1:
        digest = sha256_digest(value)
        identity = role + ":" + digest
        dependencies = tuple(sorted(set(dependencies)))
        if publish:
            publication = self.artifacts.put_with_receipt(
                identity,
                value,
                dependencies,
                publication_budget=partial(self._budget, deadline_at),
            )
            reader.expect(identity, publication.artifact)
        record = reader.get(identity)
        if (
            record.content_hash != digest
            or record.dependency_hashes != dependencies
            or reader.read(identity) != canonical_bytes(value)
        ):
            raise _invalid("retained fiscal preparation evidence differs")
        return ArtifactRefV1(
            role=role,
            artifact_id=identity,
            content_hash=digest,
            media_type="application/json",
        )

    @staticmethod
    def _period(
        quarter: FiscalQuarterReviewV1,
        evidence: dict[str, FiscalOriginalValidationEvidenceV1],
        mapped: dict[str, FiscalStatementMappingBatchV1],
    ) -> FiscalDurationPeriodV1:
        source = evidence[quarter.accession_number]
        if isinstance(source.outcome, FiscalValidationIncompleteV1):
            raise _invalid("fiscal target source is incomplete")
        claim = source.outcome.claim
        expected = quarter.period
        if (
            claim.report_period_end != expected.end
            or claim.fiscal_year_focus != expected.fiscal_year
            or claim.fiscal_period_focus != expected.fiscal_period
        ):
            raise _invalid("fiscal target differs from original DEI identity")
        cash_fact_keys = {
            item.source_fact_key
            for item in mapped[quarter.accession_number].observations
            if item.row_id
            in {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow"}
        }
        current_cash_starts = {
            fact.period_start
            for fact in claim.report.facts
            if sha256_digest(fact) in cash_fact_keys
            and fact.period_end == expected.end
            and fact.period_start is not None
        }
        if (
            not current_cash_starts
            or min(current_cash_starts) != expected.fiscal_year_start
        ):
            raise _invalid(
                "fiscal-year start differs from the disclosed primary cash-flow YTD context"
            )
        source_period = quarter.period_source
        if isinstance(source_period, FiscalFourthQuarterBoundaryV1):
            prior = evidence[source_period.preceding_accession_number]
            if isinstance(prior.outcome, FiscalValidationIncompleteV1):
                raise _invalid("preceding fiscal boundary source is incomplete")
            if (
                prior.outcome.claim.report_period_end
                != source_period.preceding_quarter_end
                or prior.outcome.claim.fiscal_year_focus != expected.fiscal_year
                or prior.outcome.claim.fiscal_period_focus != "Q3"
                or expected.start
                != source_period.preceding_quarter_end + timedelta(days=1)
                or not any(
                    fact.context_id == source_period.annual_context_id
                    and fact.period_start == expected.fiscal_year_start
                    and fact.period_end == expected.end
                    for fact in claim.report.facts
                )
            ):
                raise _invalid(
                    "fourth-quarter boundary does not follow the disclosed nine-month period"
                )
        else:
            matching = [
                item
                for item in mapped[quarter.accession_number].observations
                if item.source_locator.fact_index == source_period.fact_index
                and item.source_locator.context_id == source_period.context_id
                and item.row_id == "revenue"
            ]
            if (
                len(matching) != 1
                or not isinstance(matching[0].period, ReportedQuarterV1)
                or matching[0].period.period != expected
            ):
                raise _invalid(
                    "quarter target does not match its reported duration context"
                )
            if not any(
                fact.period_start == expected.fiscal_year_start
                and fact.period_end == expected.end
                for fact in claim.report.facts
            ):
                raise _invalid("fiscal-year start has no disclosed YTD context")
        return expected

    def _basis(
        self,
        plan: FiscalRowBasisPlanV1,
        period: FiscalDurationPeriodV1,
        observations: dict[str, FiscalObservationV1],
        filings: dict[str, FiscalBasisFilingV1],
        cutoff_at: datetime,
        component_periods: tuple[FiscalPeriodTargetV1, ...],
        reference: ArtifactRefV1,
    ) -> FiscalRevisionBasisProofV1 | None:
        if not plan.observation_ids:
            return None
        if any(identity not in observations for identity in plan.observation_ids):
            raise _invalid("reviewed basis requires a missing original observation")
        selected = tuple(observations[identity] for identity in plan.observation_ids)
        for left_id, right_id in plan.comparative_pairs:
            left, right = observations[left_id], observations[right_id]
            if (
                left.row_id != right.row_id
                or left.value != right.value
                or not left.basis.same_accounting_scope(right.basis)
                or left.period != right.period
            ):
                raise _invalid(
                    "reviewed original and comparative disclosure no longer reproduce"
                )
        bindings = tuple(
            FiscalBasisObservationV1(
                observation_id=item.observation_id,
                observation_digest=item.observation_digest,
            )
            for item in selected
        )
        pairs = tuple(
            FiscalComparativePairV1(original_id=left, comparative_id=right)
            for left, right in plan.comparative_pairs
        )
        source_filings = tuple(
            filings[accession]
            for accession in sorted({item.accession_number for item in selected})
        )
        if any(item.accepted_at > cutoff_at for item in source_filings):
            raise _invalid("reviewed revision basis was not public at cutoff")
        return FiscalRevisionBasisProofV1(
            row_id=plan.row_id,
            period=period,
            observations=bindings,
            filings=source_filings,
            comparative_pairs=pairs,
            component_period_digests=tuple(
                sha256_digest(item) for item in component_periods
            ),
            source_revision=self.pin.declared_source_revision,
            cutoff_at=cutoff_at,
            public_available_at=max(item.accepted_at for item in source_filings),
            review_evidence_ref=reference,
        )

    def prepare(
        self,
        command: FiscalPrepareCandidateCommandV2,
        *,
        deadline_at: datetime,
    ) -> CurrentFiscalCandidate:
        if self.preparation is None:
            raise SnapshotError(
                "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                "candidate preparation requires its deployment capability",
            )
        return self.preparation.prepare(command, deadline_at=deadline_at)

    def current_configuration_digest(self) -> str:
        if self.preparation is None:
            raise SnapshotError(
                "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                "candidate configuration requires its deployment composition",
            )
        return self.preparation.current_configuration_digest()

    def verify_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> CurrentFiscalCandidate:
        if self.preparation is None:
            raise SnapshotError(
                "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                "candidate verification requires its read-only deployment composition",
            )
        return self.preparation.verify_candidate(reference, deadline_at=deadline_at)

    def open_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> FiscalCandidateOperation:
        if self.preparation is None:
            raise SnapshotError(
                "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                "candidate reader is not configured",
            )
        return self.preparation.open_candidate(reference, deadline_at=deadline_at)

    def replay_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> CurrentFiscalCandidate:
        if self.preparation is None:
            raise _invalid("full replay requires its read-only deployment composition")
        return self.preparation.replay_candidate(reference, deadline_at=deadline_at)

    @contextmanager
    def _open_materialization(
        self,
        discovery_ref: ArtifactRefV1,
        *,
        security_id: str | None,
        classification_bindings: tuple[FiscalCandidateClassificationBindingV1, ...],
        deadline_at: datetime,
        publish: bool,
        retained_mapping_refs: tuple[ArtifactRefV1, ...] = (),
    ) -> Iterator[_MaterializationRead]:
        read = _MaterializationRead(self, deadline_at)
        token = _MATERIALIZATION_READS.set((*_MATERIALIZATION_READS.get(), read))
        try:
            self._materialize(
                discovery_ref,
                security_id=security_id,
                classification_bindings=classification_bindings,
                deadline_at=deadline_at,
                publish=publish,
                retained_mapping_refs=retained_mapping_refs,
                read=read,
            )
            yield read
        finally:
            read.close()
            _MATERIALIZATION_READS.reset(token)

    def _materialize(
        self,
        discovery_ref: ArtifactRefV1,
        *,
        security_id: str | None,
        classification_bindings: tuple[FiscalCandidateClassificationBindingV1, ...],
        deadline_at: datetime,
        publish: bool,
        retained_mapping_refs: tuple[ArtifactRefV1, ...] = (),
        read: _MaterializationRead,
    ) -> None:
        budget = partial(self._budget, deadline_at)
        budget()
        if self.mapping_approvals is None:
            raise SnapshotError(
                "FISCAL_MAPPING_AUTHORITY_UNCONFIGURED",
                "fiscal projection preparation requires a configured mapping authority",
            )
        reader = read.reader
        discovery = read._read_discovery(discovery_ref)
        if (
            read_retained_artifact(reader, discovery_ref) != canonical_bytes(discovery)
            or discovery.request.declared_source_revision
            != self.pin.declared_source_revision
        ):
            raise _invalid(
                "projection discovery differs from the configured source revision"
            )
        coverage = selected_fiscal_coverage(discovery)
        scopes = {
            item.accession_number: item
            for item in fiscal_primary_scopes(fiscal_statement_registry())
        }
        candidates = {
            item.filing.accession_number: item.filing
            for item in discovery.selection.candidates
            if item.filing is not None and not item.issue_codes
        }
        target_periods = tuple(item.period for item in coverage.quarters)
        policy_digest = fiscal_mapping_policy_digest()
        evidence_by_accession: dict[str, FiscalOriginalValidationEvidenceV1] = {}
        mapped: dict[str, FiscalStatementMappingBatchV1] = {}
        classifications: dict[str, FiscalCandidateClassificationBindingV1] = {}
        for binding in classification_bindings:
            source_id = binding.source_validation_ref.artifact_id
            if source_id in classifications:
                raise _invalid(
                    "candidate source has multiple supplied witness bindings"
                )
            classifications[source_id] = binding
        source_uses: list[FiscalCandidateSourceUseV1] = []
        source_evidence: list[VerifiedFiscalCandidateSource] = []
        source_documents: list[FiscalSourceDocumentObservation] = []
        source_replay_refs: list[FiscalCandidateSourceReplayRefV1] = []
        mapping_refs: list[ArtifactRefV1] = []
        filings: dict[str, FiscalBasisFilingV1] = {}
        for accession in coverage.source_accessions:
            budget()
            filing = candidates.get(accession)
            if filing is None:
                raise _invalid("reviewed source is not an eligible discovery candidate")
            resolved = ResolvedFiscalValidationRequestV1(
                selection=FiscalOriginalValidationRequestV1(
                    discovery_ref=discovery_ref, accession_number=accession
                ),
                filing=filing,
                valuation_timestamp=discovery.request.valuation_timestamp,
                pin=self.pin,
            )
            source_read = self.sources.observe(
                resolved.completed_artifact_id, deadline_at=deadline_at
            )
            reader.enroll(source_read.artifact_readset)
            evidence = source_read.evidence
            if evidence.request != resolved or isinstance(
                evidence.outcome, FiscalValidationIncompleteV1
            ):
                raise _invalid("source closure differs from requested fiscal candidate")
            if security_id is not None and security_id not in {
                fact.value.strip()
                for fact in evidence.outcome.claim.report.facts
                if fact.concept == "dei:TradingSymbol"
                and fact.entity_identifier == filing.cik
                and fact.entity_scheme == "http://www.sec.gov/CIK"
                and fact.namespace_uri is not None
                and fact.namespace_uri.startswith(
                    ("http://xbrl.sec.gov/dei/", "http://xbrl.us/dei/")
                )
            }:
                raise _invalid(
                    "security identifier is not disclosed for the source issuer"
                )
            source_ref = ArtifactRefV1(
                role="fiscal-original-validation",
                artifact_id=evidence.artifact_id,
                content_hash=sha256_digest(evidence.model_dump(mode="json")),
                media_type="application/json",
            )
            source_record = reader.get(source_ref.artifact_id)
            if (
                source_record.content_hash != source_ref.content_hash
                or source_record.media_type != source_ref.media_type
                or source_record.dependency_hashes != evidence.dependencies
            ):
                raise _invalid("source validation metadata differs from its closure")
            input_binding = source_read.retained_input_binding(source_ref)
            binding_ref = self._retain(
                input_binding,
                "fiscal-retained-input-binding-v1",
                (
                    source_ref.content_hash,
                    *(
                        item.action_result_ref.content_hash
                        for item in input_binding.inputs
                    ),
                ),
                reader,
                publish=publish,
                deadline_at=deadline_at,
            )
            source_replay_refs.append(
                FiscalCandidateSourceReplayRefV1(
                    source_validation_ref=source_ref,
                    input_binding_ref=binding_ref,
                )
            )
            archive_receipt = next(
                (
                    item
                    for item in evidence.outcome.responses
                    if item.uri == evidence.outcome.integrity.archive_uri
                ),
                None,
            )
            if archive_receipt is None:
                raise _invalid("fiscal original archive receipt is missing")
            archive = read.content.get(
                archive_receipt.content_hash, media_type=archive_receipt.media_type
            )
            budget()
            batch = map_fiscal_primary_source(
                evidence,
                source_ref,
                archive=archive,
                reviewed=scopes[accession],
                target_periods=target_periods,
                security_id=security_id,
                policy_digest=policy_digest,
                check_deadline=budget,
                consume_inputs=read.mapping_consumption.append,
            )
            source_documents.append(
                FiscalSourceDocumentObservation(
                    source_validation_ref=source_ref,
                    primary_document_url=evidence.outcome.claim.source.uri,
                    primary_document_sha256=evidence.outcome.integrity.raw_content_hash,
                    archive_member_sha256=evidence.outcome.integrity.archive_member_hash,
                )
            )
            if isinstance(evidence.outcome, FiscalValidationCompleteRefusedV1):
                if self.classifications is None:
                    raise SnapshotError(
                        "FISCAL_CLASSIFICATION_UNCONFIGURED",
                        "raw-refused candidate source requires an independent classification owner",
                    )
                if source_ref.artifact_id not in classifications:
                    raise SnapshotError(
                        "FISCAL_WITNESS_REQUIRED",
                        "raw-refused candidate source requires its exact retained witness",
                    )
                if (
                    classifications[source_ref.artifact_id].source_validation_ref
                    != source_ref
                ):
                    raise _invalid(
                        "classification reference differs from the exact source"
                    )
            classification = classifications.get(source_ref.artifact_id)
            if classification is not None and not isinstance(
                evidence.outcome, FiscalValidationCompleteRefusedV1
            ):
                raise _invalid(
                    "raw-pass source cannot consume a refusal classification"
                )
            use_scope = FiscalSourceUseScopeV1(
                source_validation_ref=source_ref,
                validation_kind=evidence.outcome.kind,
                source_binding_digest=batch.source_binding_digest,
                issuer_id=filing.cik,
                accession_number=accession,
                cutoff_at=discovery.request.valuation_timestamp,
                runtime=evidence.outcome.runtime,
                raw_report_digest=sha256_digest(
                    evidence.outcome.claim.report.model_dump(mode="json")
                ),
                parser_action_refs=evidence.outcome.action_refs,
                witness_ref=classification.witness_ref
                if classification is not None
                else None,
                display_profile_digest=fiscal_display_profile_digest(),
                mapping_policy_digest=policy_digest,
                permitted_inputs=batch.observations,
            )
            if isinstance(evidence.outcome, FiscalValidationCompleteRefusedV1):
                if self.classifications is None:
                    raise _invalid("candidate classification owner became unavailable")
                if classification is None:
                    raise _invalid("candidate source has no classification binding")
                read_retained_artifact(reader, classification.witness_ref)
                for reference in classification.classification_refs:
                    read_retained_artifact(reader, reference)
                admission = read.children.enter_context(
                    self.classifications.open_candidate_source(
                        use_scope,
                        classification.classification_refs,
                        deadline_at=deadline_at,
                    )
                )
                admitted = admission.current()
                read.sources.append(
                    _ClassifiedMaterializedSource(source_read, admission, admitted)
                )
                if admitted.source_use.scope != use_scope:
                    raise _invalid(
                        "classification does not authorize the exact requested source use"
                    )
                source_uses.append(admitted.source_use)
                source_evidence.append(admitted)
                for record in admitted.consumed_metadata:
                    reader.expect(record.artifact_id, record)
                reader.enroll(admission.artifact_readset)
            else:
                raw_use = VerifiedRawSourceForCandidateV1(scope=use_scope)
                source_uses.append(raw_use)
                raw_proof = VerifiedRawCandidateSource(
                    raw_use,
                    evidence.outcome.action_refs,
                    tuple(
                        record
                        for _, record in source_read.records
                        if record is not None
                    ),
                )
                source_evidence.append(raw_proof)
                read.sources.append(_RawMaterializedSource(source_read, raw_proof))
            mapping_reader = reader.for_consumer()
            read.mapping_reads.append(mapping_reader)
            batch_ref = self._retain(
                batch,
                "fiscal-statement-mapping-v1",
                (source_ref.content_hash, batch.primary_scope_digest, policy_digest),
                mapping_reader,
                publish=publish,
                deadline_at=deadline_at,
            )
            if publish:
                if self.mapping_publications is None:
                    raise SnapshotError(
                        "FISCAL_MAPPING_AUTHORITY_UNCONFIGURED",
                        "mapping write capability is not configured",
                    )
                approval_ref = self.mapping_publications.approve(
                    batch, batch_ref, deadline_at=deadline_at
                )
            else:
                position = len(mapping_refs) + 1
                if position >= len(retained_mapping_refs):
                    raise _invalid(
                        "candidate lacks its exact retained mapping approval"
                    )
                approval_ref = retained_mapping_refs[position]
                if approval_ref.role != "fiscal-mapping-approval":
                    raise _invalid("retained mapping approval role differs")
            self.mapping_approvals.verify(batch, approval_ref, deadline_at=deadline_at)
            read_retained_artifact(mapping_reader, approval_ref)
            read.approvals.append((batch, approval_ref))
            mapping_refs.extend((batch_ref, approval_ref))
            disclosure_refs = tuple(
                self._retain(
                    item,
                    "fiscal-accounting-disclosure-v1",
                    (source_ref.content_hash, item.primary_member_sha256),
                    mapping_reader,
                    publish=publish,
                    deadline_at=deadline_at,
                )
                for item in batch.disclosures
            )
            filings[accession] = FiscalBasisFilingV1(
                accession_number=accession,
                primary_document_sha256=scopes[accession].primary_member_sha256,
                accepted_at=filing.accepted_at,
                disclosure_refs=disclosure_refs,
            )
            evidence_by_accession[accession], mapped[accession] = evidence, batch
        if set(classifications) != {
            item.scope.source_validation_ref.artifact_id
            for item in source_uses
            if isinstance(item, ClassifiedSourceForCandidateV1)
        }:
            raise _invalid(
                "classification bindings differ from the exact refused source set"
            )
        source_set_digest = sha256_digest(tuple(source_uses))
        targets = tuple(
            FiscalPeriodTargetV1(
                period_id="fiscal-quarter-v1:"
                + sha256_digest(
                    (
                        coverage.issuer_id,
                        security_id,
                        item.period,
                        discovery.request.valuation_timestamp,
                        source_set_digest,
                        policy_digest,
                    )
                ),
                period=self._period(item, evidence_by_accession, mapped),
                cutoff_at=discovery.request.valuation_timestamp,
                source_binding_digest=source_set_digest,
            )
            for item in coverage.quarters
        )
        by_end = {
            item.period.end: item
            for item in targets
            if isinstance(item.period, FiscalDurationPeriodV1)
        }
        windows = tuple(
            FiscalTtmWindowV1(
                window_id="fiscal-ttm-v1:"
                + sha256_digest(tuple(by_end[end] for end in item.quarter_ends)),
                quarters=tuple(by_end[end] for end in item.quarter_ends),
                source_binding_digest=source_set_digest,
            )
            for item in coverage.ttm_windows
        )
        observations = tuple(
            item for batch in mapped.values() for item in batch.observations
        )
        by_id = {item.observation_id: item for item in observations}
        cohort_review = FiscalCoverageBasisEvidenceV1(
            coverage=coverage,
            observations=tuple(
                FiscalBasisObservationV1(
                    observation_id=item.observation_id,
                    observation_digest=item.observation_digest,
                )
                for item in observations
            ),
            filings=tuple(filings[key] for key in sorted(filings)),
            source_revision=self.pin.declared_source_revision,
            cutoff_at=discovery.request.valuation_timestamp,
            source_set_digest=source_set_digest,
            mapping_refs=tuple(mapping_refs),
        )
        review_ref = self._retain(
            cohort_review,
            "fiscal-basis-review-v1",
            tuple(ref.content_hash for ref in mapping_refs)
            + tuple(
                ref.content_hash
                for filing in filings.values()
                for ref in filing.disclosure_refs
            ),
            read.basis_read,
            publish=publish,
            deadline_at=deadline_at,
        )
        proofs = []
        for quarter in coverage.quarters:
            for plan in quarter.rows:
                budget()
                proof = self._basis(
                    plan,
                    quarter.period,
                    by_id,
                    filings,
                    discovery.request.valuation_timestamp,
                    (),
                    review_ref,
                )
                if proof is not None:
                    proofs.append(proof)
        for review, window in zip(coverage.ttm_windows, windows, strict=True):
            first, last = window.quarters[0].period, window.quarters[-1].period
            if not isinstance(first, FiscalDurationPeriodV1) or not isinstance(
                last, FiscalDurationPeriodV1
            ):
                raise _invalid("reviewed TTM components are not duration quarters")
            period = first.model_copy(
                update={
                    "end": last.end,
                    "fiscal_year": last.fiscal_year,
                    "fiscal_period": "TTM",
                    "inclusive_days": (last.end - first.start).days + 1,
                }
            )
            for plan in review.rows:
                budget()
                proof = self._basis(
                    plan,
                    period,
                    by_id,
                    filings,
                    discovery.request.valuation_timestamp,
                    window.quarters,
                    review_ref,
                )
                if proof is not None:
                    proofs.append(proof)
        scope = StatementScopeV1(
            issuer_id=coverage.issuer_id,
            security_id=security_id,
            security_scope="issuer",
            entity_scope=coverage.issuer_id,
            currency="USD",
            unit="iso4217:USD",
        )
        projection_input = FiscalProjectionInputV1(
            observations=observations,
            scope=scope,
            quarter_targets=targets,
            ttm_windows=windows,
            cutoff_at=discovery.request.valuation_timestamp,
            source_binding_digest=source_set_digest,
            basis_proofs=tuple(proofs),
            source_revision=self.pin.declared_source_revision,
            executable_digest=fiscal_projection_executable_digest(),
        )
        projection_input = FiscalProjectionInputV1.model_validate_json(
            canonical_bytes(projection_input)
        )
        projection_input_ref = self._retain(
            projection_input,
            "fiscal-statement-projection-input-v1",
            tuple(ref.content_hash for ref in mapping_refs)
            + (review_ref.content_hash, source_set_digest),
            read.basis_read,
            publish=publish,
            deadline_at=deadline_at,
        )
        projection = project_fiscal_statements(projection_input)
        budget()
        projection_ref = self._retain(
            projection,
            "fiscal-statement-projection-v1",
            tuple(ref.content_hash for ref in mapping_refs)
            + tuple(item.review_evidence_ref.content_hash for item in proofs),
            read.basis_read,
            publish=publish,
            deadline_at=deadline_at,
        )
        if set(classifications) != {
            source.scope.source_validation_ref.artifact_id
            for source in source_uses
            if isinstance(source, ClassifiedSourceForCandidateV1)
        }:
            raise _invalid("candidate classification bindings include unused sources")
        candidate = FiscalCandidateContentV2(
            discovery_ref=discovery_ref,
            materialization=self.pin,
            scope=scope,
            cutoff_at=discovery.request.valuation_timestamp,
            source_uses=tuple(source_uses),
            mapping_refs=tuple(mapping_refs),
            projection_ref=projection_ref,
            projection_input_ref=projection_input_ref,
            period_set_digest=sha256_digest((targets, windows)),
            row_lineage_digest=sha256_digest(
                tuple(
                    (item.node_id, item.input_edges, item.verification_edges)
                    for item in projection.nodes
                )
            ),
            source_set_digest=source_set_digest,
            projection_policy_digest=fiscal_statement_policy().digest,
            executable_digest=fiscal_projection_executable_digest(),
            basis_review_ref=review_ref,
            source_replay_refs=tuple(source_replay_refs),
        )
        read.image = FiscalCandidateMaterialization(
            content=candidate,
            projection=projection,
            source_evidence=tuple(source_evidence),
            source_documents=tuple(source_documents),
            consumed_metadata=tuple(
                record for _, record in reader.records if record is not None
            ),
            correctness=self._correctness(candidate, read),
            artifact_readset=reader.readset,
            content_readsets=read._content_readsets(),
        )
