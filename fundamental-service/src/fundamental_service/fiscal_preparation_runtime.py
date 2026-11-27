from __future__ import annotations

import os
import hashlib
import stat
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ConfigDict, Field

from .command_artifacts import EvidenceArtifactStore
from .contracts import StrictModel
from .data_releases import DataReleaseTrustRootsV1
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    FiscalAdmissionHistoryReaderPort,
    PostgresFiscalAdmissionHistory,
    ReadOnlyFiscalAdmissionHistory,
)
from .fiscal_authority_contracts import FiscalAuthorityDeploymentV1
from .fiscal_candidate_preparation import FiscalCandidatePreparation
from .fiscal_classification_source import (
    FiscalClassificationSourcePort,
    FiscalClassificationSourceResolver,
)
from .fiscal_discovery import FiscalDiscovery
from .fiscal_projection_builder import FiscalProjectionBuilder
from .fiscal_source_classification import FiscalSourceClassificationOwner
from .fiscal_source_closure import FiscalSourceClosure
from .fiscal_statement_mapping import FiscalMappingApprovalOwner, FiscalMappingVerifier
from .fiscal_validation_contracts import FiscalValidationPinV1
from .metadata import PostgresMetadataStore, PostgresArtifactStore, PostgresContentStore
from .source_acquisition import SecAcquisitionUseCase
from .serialization import sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError
from .fiscal_source_preparation import (
    FiscalSourceProducerEvidenceVerifier,
    AccountingAccreditationProvider,
)
from .fiscal_source_producer_runtime import public_accounting_accreditation_provider


class FiscalPreparationDeploymentV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    authority_deployment_file: Path
    candidate_authority_id: str = Field(min_length=1, max_length=256)
    mapping_trust_roots_file: Path
    candidate_private_key_file: Path | None = None
    mapping_private_key_file: Path | None = None

    @classmethod
    def from_env(cls, *, write: bool) -> FiscalPreparationDeploymentV1:
        roster = os.getenv("FUNDAMENTAL_FISCAL_AUTHORITY_DEPLOYMENT_FILE")
        authority_id = os.getenv("FUNDAMENTAL_FISCAL_CANDIDATE_AUTHORITY_ID")
        trust = os.getenv("FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE")
        if not roster or not authority_id or not trust:
            raise SnapshotError(
                "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                "candidate roster, machine authority and mapping trust roots are required",
            )
        candidate = (
            os.getenv("FUNDAMENTAL_FISCAL_CANDIDATE_PRIVATE_KEY_FILE")
            if write
            else None
        )
        mapping = (
            os.getenv("FUNDAMENTAL_FISCAL_MAPPING_PRIVATE_KEY_FILE") if write else None
        )
        return cls(
            authority_deployment_file=Path(roster),
            candidate_authority_id=authority_id,
            mapping_trust_roots_file=Path(trust),
            candidate_private_key_file=Path(candidate) if candidate else None,
            mapping_private_key_file=Path(mapping) if mapping else None,
        )


@dataclass(frozen=True)
class FiscalPreparationInputs:
    artifacts: EvidenceArtifactStore
    content: ContentAddressedStore
    discovery: FiscalDiscovery
    sources: FiscalSourceClosure
    pin: FiscalValidationPinV1
    classification_sources: FiscalClassificationSourcePort | None
    source_configuration_digest: Callable[[], str] = lambda: "no-source-configuration"
    accounting_accreditation: AccountingAccreditationProvider | None = None


def _configuration(path: Path, *, private: bool = False) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size > 1024 * 1024
            or private
            and (info.st_mode & 0o077 or info.st_uid != os.getuid())
        ):
            raise SnapshotError(
                "FISCAL_CANDIDATE_CONFIGURATION_INVALID",
                "candidate deployment file permissions or bounds are invalid",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise SnapshotError(
                "FISCAL_CANDIDATE_CONFIGURATION_INVALID",
                "candidate deployment file exceeds its byte limit",
            )
        return raw
    finally:
        os.close(descriptor)


def _private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(
        _configuration(path, private=True), password=None
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise SnapshotError(
            "FISCAL_CANDIDATE_CONFIGURATION_INVALID",
            "candidate runtime requires Ed25519 deployment keys",
        )
    return key


def build_fiscal_candidate_runtime(
    inputs: FiscalPreparationInputs,
    metadata: PostgresMetadataStore,
    deployment: FiscalPreparationDeploymentV1,
    *,
    write: bool,
) -> FiscalProjectionBuilder:
    if not write:
        inputs = replace(
            inputs,
            artifacts=inputs.artifacts.as_read_only()
            if isinstance(inputs.artifacts, PostgresArtifactStore)
            else inputs.artifacts,
            content=inputs.content.as_read_only()
            if isinstance(inputs.content, PostgresContentStore)
            else inputs.content,
        )
    read_artifacts = (
        inputs.artifacts.as_read_only()
        if isinstance(inputs.artifacts, PostgresArtifactStore)
        else inputs.artifacts
    )
    read_operation: Callable[[], AbstractContextManager[Callable[[], None]]]
    if isinstance(read_artifacts, PostgresArtifactStore):
        read_operation = read_artifacts.scoped_read_operation
    else:

        def unretained_read_operation() -> AbstractContextManager[Callable[[], None]]:
            return nullcontext(lambda: None)

        read_operation = unretained_read_operation
    history: FiscalAdmissionHistoryReaderPort = PostgresFiscalAdmissionHistory(metadata)
    if not write:
        history = ReadOnlyFiscalAdmissionHistory(history)
    authorities = FiscalAuthorityOwner(
        artifacts=read_artifacts,
        history=history,
        deployment=lambda: FiscalAuthorityDeploymentV1.model_validate_json(
            _configuration(deployment.authority_deployment_file)
        ),
    )
    accounting_accreditation = (
        inputs.accounting_accreditation or public_accounting_accreditation_provider()
    )
    classifier = FiscalSourceClassificationOwner(
        artifacts=read_artifacts,
        history=history,
        authorities=authorities,
        sources=inputs.classification_sources,
        producer_evidence=FiscalSourceProducerEvidenceVerifier(
            accounting_accreditation
        ),
        require_production_evidence=True,
    )

    def accounting_generation() -> str:
        try:
            return sha256_digest(accounting_accreditation())
        except (SnapshotError, ValueError):
            return "accounting-release-unavailable"

    def roots() -> DataReleaseTrustRootsV1:
        return DataReleaseTrustRootsV1.model_validate_json(
            _configuration(deployment.mapping_trust_roots_file)
        )

    mapping_publications: FiscalMappingApprovalOwner | None = None
    candidate_path, mapping_path = (
        deployment.candidate_private_key_file,
        deployment.mapping_private_key_file,
    )
    if write:
        if candidate_path is None or mapping_path is None:
            raise SnapshotError(
                "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                "candidate and mapping write capabilities are required",
            )
        mapping_publications = FiscalMappingApprovalOwner(
            artifacts=inputs.artifacts,
            trust_roots=roots,
            private_key=lambda: _private_key(mapping_path),
        )
    mapping = FiscalMappingVerifier(artifacts=read_artifacts, trust_roots=roots)
    builder = FiscalProjectionBuilder(
        discovery=inputs.discovery,
        sources=inputs.sources,
        artifacts=inputs.artifacts,
        read_artifacts=read_artifacts,
        content=inputs.content.as_read_only()
        if isinstance(inputs.content, PostgresContentStore)
        else inputs.content,
        pin=inputs.pin,
        mapping_approvals=mapping,
        mapping_publications=mapping_publications,
        classifications=classifier,
    )

    @contextmanager
    def capture_lock(key: str, deadline_at: datetime) -> Iterator[None]:
        lease = metadata.try_acquire_ingestion_lock(key)
        if lease is None:
            raise SnapshotError(
                "FISCAL_CANDIDATE_IN_FLIGHT",
                "candidate command is already executing",
                retryable=True,
            )
        try:
            yield
        finally:
            metadata.release_ingestion_lock(lease)

    builder.preparation = FiscalCandidatePreparation(
        builder=builder,
        artifacts=inputs.artifacts,
        read_artifacts=read_artifacts,
        history=history,
        authorities=authorities,
        authority_id=deployment.candidate_authority_id,
        read_operation=read_operation,
        configuration_digest=lambda: sha256_digest(
            (
                hashlib.sha256(
                    _configuration(deployment.authority_deployment_file)
                ).hexdigest(),
                hashlib.sha256(
                    _configuration(deployment.mapping_trust_roots_file)
                ).hexdigest(),
                inputs.source_configuration_digest(),
                accounting_generation(),
            )
        ),
        capture_lock=capture_lock if write else None,
        private_key=(lambda: _private_key(candidate_path))
        if write and candidate_path is not None
        else None,
    )
    return builder


def configured_fiscal_candidate_runtime(
    acquisition: SecAcquisitionUseCase,
    metadata: PostgresMetadataStore,
    *,
    declared_source_revision: str,
    write: bool,
) -> FiscalProjectionBuilder:
    if not isinstance(
        acquisition.content_store, PostgresContentStore
    ) or not isinstance(acquisition.capture_store, PostgresArtifactStore):
        raise SnapshotError(
            "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
            "candidate observations require PostgreSQL read-only storage",
        )
    writer_artifacts, writer_content = (
        acquisition.capture_store,
        acquisition.content_store,
    )
    acquisition = SecAcquisitionUseCase(
        adapter=acquisition.adapter,
        ingestion=acquisition.ingestion,
        metadata=metadata,
        content_store=acquisition.content_store.as_read_only(),
        settings=acquisition.settings,
        authorized_organizations=acquisition.authorized_organizations,
        capture_store=acquisition.capture_store.as_read_only(),
    )
    sources = acquisition.fiscal_source_closure(
        declared_source_revision=declared_source_revision
    )
    discovery = acquisition.fiscal_discovery()
    if acquisition.capture_store is None:
        raise SnapshotError(
            "SEC_CAPTURE_STORE_UNAVAILABLE",
            "candidate evidence persistence is unavailable",
        )

    def source_configuration_digest() -> str:
        focus = os.getenv("FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE")
        return (
            hashlib.sha256(_configuration(Path(focus))).hexdigest()
            if focus
            else "focus-unconfigured"
        )

    inputs = FiscalPreparationInputs(
        writer_artifacts if write else acquisition.capture_store,
        writer_content if write else acquisition.content_store,
        discovery,
        sources,
        FiscalValidationPinV1(
            declared_source_revision=declared_source_revision,
            taxonomy_manifest_id=acquisition.settings.taxonomy_manifest_id,
        ),
        FiscalClassificationSourceResolver(
            sources=sources,
            discovery=discovery,
            witnesses=acquisition.fiscal_focus_witness(
                declared_source_revision=declared_source_revision, read_only=True
            ),
            content=acquisition.content_store,
        ),
        source_configuration_digest,
    )
    return build_fiscal_candidate_runtime(
        inputs,
        metadata,
        FiscalPreparationDeploymentV1.from_env(write=write),
        write=write,
    )
