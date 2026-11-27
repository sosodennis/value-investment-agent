from __future__ import annotations

import hashlib
import base64
import os
import re
import stat
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.exc import SQLAlchemyError

from .artifact_evidence import read_retained_artifact
from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    PostgresFiscalAdmissionHistory,
    ReadOnlyFiscalAdmissionHistory,
)
from .fiscal_authority_contracts import (
    CurrentFiscalAuthorityV1,
    FiscalAuthorityDeploymentV1,
)
from .fiscal_classification_contracts import (
    FiscalClassifierActorV1,
    FiscalClassifierReviewExecutionV1,
    FiscalRecordClassificationCommandV2,
    FiscalSourcePreparationExecutionV1,
    SignedFiscalSourceClassificationV2,
    FiscalClassificationPublicationV2,
    FiscalSourceAccountingReviewV1,
)
from .fiscal_classification_source import (
    FiscalClassificationSourcePort,
    FiscalClassificationSourceResolver,
)
from .fiscal_source_accounting_policy import (
    evaluate_source_accounting,
    source_accounting_policy_identity,
)
from .fiscal_source_accounting_policy_contracts import encode_accounting_record
from .fiscal_source_accounting_policy_contracts import read_accounting_record
from .fiscal_source_classification import (
    ClassificationCommand,
    SignedClassification,
    FiscalSourceClassificationOwner,
)
from .fiscal_source_closure import FiscalArtifactRead, FiscalSourceClosure
from .fiscal_source_preparation import (
    AccountingAccreditationProvider,
    FiscalSourceProducerEvidenceVerifier,
    fiscal_source_producer_executable_digest,
    producer_invalid,
    read_source_preparation,
    read_source_content,
    read_producer_invocation,
    source_content_references,
)
from .fiscal_source_producer_contracts import (
    FiscalAccountingAccreditationV1,
    FiscalAccountingRefusalExecutionV1,
    FiscalClassifierReviewExecutionV2,
    FiscalProducerInvocationV1,
    FiscalProducerOrderV1,
    FiscalSourcePreparationExecutionV2,
    SignedFiscalSourcePreparationExecutionV2,
)
from .fiscal_validation_contracts import FiscalValidationCompleteRefusedV1
from .history_recovery_contracts import FiscalIssuanceContextV1
from .metadata import (
    IngestionLockLease,
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    metadata_operation_budget,
)
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .source_acquisition import SecAcquisitionUseCase

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")
_DIRECTORY = Path("/etc/fundamental/fiscal-source-producers")


class FiscalSourceContentReaderPort(Protocol):
    def get(self, content_hash: str, *, media_type: str) -> bytes: ...


def _budget(deadline_at: datetime) -> float:
    now = datetime.now(UTC)
    if deadline_at.utcoffset() is None or now >= deadline_at:
        raise SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED",
            "source producer deadline expired",
            retryable=True,
        )
    return (deadline_at - now).total_seconds()


def _public_signature(
    message: bytes, signature: str, authority: CurrentFiscalAuthorityV1
) -> None:
    Ed25519PublicKey.from_public_bytes(
        base64.b64decode(
            authority.grant.identity.public_key_ed25519_base64, validate=True
        )
    ).verify(bytes.fromhex(signature), message)


def _protected(
    path: Path, *, owner: int, private: bool = False, limit: int = 16384
) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise producer_invalid("producer deployment path must be absolute")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
            info = os.fstat(child)
            if info.st_uid not in {0, owner} or info.st_mode & 0o022:
                os.close(child)
                raise producer_invalid("producer deployment ancestry is not protected")
            os.close(directory)
            directory = child
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != owner
                or info.st_mode & (0o077 if private else 0o022)
                or info.st_size > limit
            ):
                raise producer_invalid("producer deployment custody or bounds differ")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise producer_invalid("producer deployment exceeds byte limit")
            return raw
        finally:
            os.close(descriptor)
    except OSError as error:
        raise producer_invalid(
            "producer deployment is unavailable or unsafe"
        ) from error
    finally:
        os.close(directory)


class FiscalSourceProducerInstallationV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-source-producer-installation.v1"] = (
        "fundamental.fiscal-source-producer-installation.v1"
    )
    role: Literal["source_preparer", "classifier"]
    audience: str = Field(min_length=1, max_length=256)
    authority_id: str = Field(min_length=1, max_length=256)
    workload_uid: int = Field(ge=0)
    deployment_uid: int = Field(ge=0)
    database_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    deployment_file: Path
    orders_directory: Path
    private_key_file: Path
    accreditation_file: Path | None = None
    source_configuration_files: tuple[Path, ...] = Field(max_length=32)
    declared_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    executable_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Intent(StrictModel):
    model_config = ConfigDict(frozen=True)
    order: FiscalProducerOrderV1
    installation_digest: str


class _Signing(StrictModel):
    model_config = ConfigDict(frozen=True)
    invocation_ref: ArtifactRefV1
    message_digest: str


class _Completed(StrictModel):
    model_config = ConfigDict(frozen=True)
    command: FiscalRecordClassificationCommandV2
    actor: FiscalClassifierActorV1


class _Outcome(StrictModel):
    model_config = ConfigDict(frozen=True)
    body: (
        SignedFiscalSourceClassificationV2
        | SignedFiscalSourcePreparationExecutionV2
        | FiscalAccountingRefusalExecutionV1
    )
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")


def producer_reference(record: ArtifactRecordV1, role: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def public_accounting_accreditation_provider(
    path: Path = _DIRECTORY / "accounting-release.json", *, owner: int = 0
) -> AccountingAccreditationProvider:
    def current() -> ArtifactRefV1:
        raw = _protected(path, owner=owner)
        ref = ArtifactRefV1.model_validate_json(raw)
        if (
            canonical_bytes(ref) != raw
            or ref.role != "fiscal-accounting-accreditation-v1"
            or ref.media_type != "application/json"
        ):
            raise producer_invalid("installed accounting release reference differs")
        return ref

    return current


def load_source_producer_installation(
    role: Literal["source_preparer", "classifier"],
) -> FiscalSourceProducerInstallationV1:
    raw = _protected(_DIRECTORY / (role + ".json"), owner=0)
    try:
        installation = FiscalSourceProducerInstallationV1.model_validate_json(raw)
    except ValueError as error:
        raise producer_invalid("producer installation failed typed decoding") from error
    if (
        canonical_bytes(installation.model_dump(mode="json")) != raw
        or installation.role != role
        or installation.workload_uid == 0
        or installation.workload_uid == installation.deployment_uid
    ):
        raise producer_invalid("producer installation requires an independent workload")
    return installation


def configured_source_producer_runtime(
    acquisition: SecAcquisitionUseCase,
    metadata: PostgresMetadataStore,
    *,
    role: Literal["source_preparer", "classifier"],
) -> FiscalSourceProducerRuntime:
    installation = load_source_producer_installation(role)
    if not isinstance(
        acquisition.capture_store, PostgresArtifactStore
    ) or not isinstance(acquisition.content_store, PostgresContentStore):
        raise producer_invalid("source producer requires PostgreSQL retained evidence")
    artifacts = acquisition.capture_store
    source_content = acquisition.content_store.as_read_only()
    if role == "classifier":
        acquisition = SecAcquisitionUseCase(
            adapter=acquisition.adapter,
            ingestion=acquisition.ingestion,
            metadata=metadata,
            content_store=source_content,
            settings=acquisition.settings,
            authorized_organizations=acquisition.authorized_organizations,
            capture_store=artifacts.as_read_only(),
        )
    sources = acquisition.fiscal_source_closure(
        declared_source_revision=installation.declared_source_revision
    )
    resolver = (
        FiscalClassificationSourceResolver(
            sources=sources,
            discovery=acquisition.fiscal_discovery(),
            witnesses=acquisition.fiscal_focus_witness(
                declared_source_revision=installation.declared_source_revision,
                read_only=True,
            ),
            content=acquisition.content_store,
        )
        if role == "classifier"
        else None
    )
    return FiscalSourceProducerRuntime(
        installation=installation,
        artifacts=artifacts,
        metadata=metadata,
        sources=sources,
        content=source_content,
        classification_sources=resolver,
        installation_file=_DIRECTORY / (role + ".json"),
    )


class FiscalSourceProducerRuntime:
    def __init__(
        self,
        *,
        installation: FiscalSourceProducerInstallationV1,
        artifacts: PostgresArtifactStore,
        metadata: PostgresMetadataStore,
        sources: FiscalSourceClosure,
        content: FiscalSourceContentReaderPort,
        classification_sources: FiscalClassificationSourcePort | None,
        installation_file: Path | None = None,
    ) -> None:
        self.installation, self.artifacts, self.metadata = (
            installation,
            artifacts,
            metadata,
        )
        self.sources, self.classification_sources = sources, classification_sources
        self.content = content
        self.installation_file = installation_file
        self.history = PostgresFiscalAdmissionHistory(metadata)
        self.authorities = FiscalAuthorityOwner(
            artifacts=artifacts.as_read_only(),
            history=ReadOnlyFiscalAdmissionHistory(self.history),
            deployment=self._deployment,
        )

    def _deployment(self) -> FiscalAuthorityDeploymentV1:
        raw = _protected(
            self.installation.deployment_file,
            owner=self.installation.deployment_uid,
            limit=1024 * 1024,
        )
        deployment = FiscalAuthorityDeploymentV1.model_validate_json(raw)
        if canonical_bytes(deployment) != raw:
            raise producer_invalid("producer authority roster is not canonical")
        return deployment

    def _order(self, identity: str) -> FiscalProducerOrderV1:
        if _ID.fullmatch(identity) is None:
            raise producer_invalid("producer order identifier is invalid")
        raw = _protected(
            self.installation.orders_directory / (identity + ".json"),
            owner=self.installation.deployment_uid,
        )
        try:
            result = FiscalProducerOrderV1.model_validate_json(raw)
        except ValueError as error:
            raise producer_invalid("producer order failed typed decoding") from error
        if canonical_bytes(result) != raw or result.order_id != identity:
            raise producer_invalid("producer order canonical identity differs")
        return result

    def _generation(self) -> str:
        installed = self.installation
        return sha256_digest(
            (
                installed.model_dump(mode="json"),
                self._deployment(),
                tuple(
                    (
                        str(path),
                        hashlib.sha256(
                            _protected(
                                path, owner=installed.deployment_uid, limit=1024 * 1024
                            )
                        ).hexdigest(),
                    )
                    for path in installed.source_configuration_files
                ),
                public_accounting_accreditation_provider(
                    installed.accreditation_file, owner=installed.deployment_uid
                )()
                if installed.accreditation_file is not None
                else None,
            )
        )

    def _require(
        self,
        order: FiscalProducerOrderV1,
        lease: IngestionLockLease,
        generation: str,
        deadline_at: datetime,
    ) -> CurrentFiscalAuthorityV1:
        _budget(deadline_at)
        installed = self.installation
        if self.installation_file is not None and _protected(
            self.installation_file, owner=0
        ) != canonical_bytes(installed.model_dump(mode="json")):
            raise producer_invalid("installed source producer trust changed")

        async def identity(connection: AsyncConnection) -> tuple[str, str]:
            row = (
                await connection.execute(text("SELECT current_user, session_user"))
            ).one()
            return str(row[0]), str(row[1])

        if (
            os.getuid() != installed.workload_uid
            or self.metadata.run_fiscal_admission_history(identity)
            != (installed.database_role, installed.database_role)
        ):
            raise producer_invalid("source producer OS or database workload differs")
        database_now = self.metadata.require_ingestion_lock(lease)
        now = datetime.now(UTC)
        if (
            self._order(order.order_id) != order
            or order.role != installed.role
            or order.audience != installed.audience
            or order.authority_id != installed.authority_id
            or order.executable_digest != installed.executable_digest
            or installed.executable_digest != fiscal_source_producer_executable_digest()
            or order.deployment_digest != sha256_digest(self._deployment())
            or self._generation() != generation
            or not order.valid_from <= now < order.expires_at
            or not order.valid_from <= database_now < order.expires_at
        ):
            raise producer_invalid(
                "source producer order, build, deployment or validity differs"
            )
        authority = self.authorities.read_current(
            order.authority_id, expected_role=order.role, deadline_at=deadline_at
        )
        if (
            authority.grant.identity.principal_kind != "machine"
            or order.expires_at > authority.grant.valid_until
        ):
            raise producer_invalid("source producer requires current machine authority")
        epoch = self.history.read_epoch(deadline_at=deadline_at)
        try:
            epoch.require_current_issuance(order.issuance)
        except ValueError as error:
            raise producer_invalid("producer order belongs to another epoch") from error
        if order.role == "classifier":
            command_id = "fiscal-source-classification-v2:" + sha256_digest(
                {"authority_id": order.authority_id, "command_id": order.order_id}
            )
            stream = "control:fiscal-classification:" + command_id
            state = self.history.read_if_present(stream, deadline_at=deadline_at)
            current = state.heads[0] if state else None
            if current != order.expected_head:
                if (
                    state is None
                    or len(state.entries) != 1
                    or state.entries[0].event.body.kind != "control"
                    or state.entries[0].event.body.payload_ref.artifact_id != command_id
                    or order.expected_head is not None
                ):
                    raise producer_invalid(
                        "classification expected control head differs"
                    )
        return authority

    def _key(self, authority: CurrentFiscalAuthorityV1) -> Ed25519PrivateKey:
        raw = _protected(
            self.installation.private_key_file,
            owner=self.installation.workload_uid,
            private=True,
        )
        try:
            key = serialization.load_pem_private_key(raw, password=None)
        except (ValueError, TypeError) as error:
            raise producer_invalid("source producer private key is invalid") from error
        if (
            not isinstance(key, Ed25519PrivateKey)
            or hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest()
            != authority.grant.identity.key_id
        ):
            raise producer_invalid("source producer key differs from current role")
        return key

    def run(
        self, protected_order_id: str, *, deadline_at: datetime
    ) -> ArtifactRefV1 | FiscalClassificationPublicationV2:
        with metadata_operation_budget(
            partial(_budget, deadline_at),
            lambda: SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED",
                "source producer deadline expired",
                retryable=True,
            ),
        ):
            _budget(deadline_at)
            order = self._order(protected_order_id)
            work_key = sha256_digest(
                (
                    "fiscal-source-producer",
                    order.role,
                    order.authority_id,
                    order.order_id,
                )
            )
            lease = self.metadata.try_acquire_ingestion_lock(work_key)
            if lease is None:
                raise SnapshotError(
                    "FISCAL_SOURCE_PRODUCER_IN_FLIGHT",
                    "producer order is already executing",
                    retryable=True,
                )
            try:
                generation = self._generation()
                authority = self._require(order, lease, generation, deadline_at)
                job = _ProducerJob(
                    self, order, lease, generation, authority, work_key, deadline_at
                )
                result = (
                    job.prepare() if order.role == "source_preparer" else job.classify()
                )
                job.live()
                return result
            except ValueError as error:
                raise producer_invalid(
                    "source producer retained evidence failed typed verification"
                ) from error
            except InvalidSignature as error:
                raise producer_invalid(
                    "source producer signature is invalid"
                ) from error
            except SQLAlchemyError as error:
                raise SnapshotError(
                    "FISCAL_SOURCE_PRODUCER_STORAGE_FAILED",
                    "source producer storage operation failed",
                    retryable=True,
                ) from error
            finally:
                self.metadata.release_ingestion_lock(lease)


class _ProducerJob:
    def __init__(
        self,
        runtime: FiscalSourceProducerRuntime,
        order: FiscalProducerOrderV1,
        lease: IngestionLockLease,
        generation: str,
        authority: CurrentFiscalAuthorityV1,
        work_key: str,
        deadline_at: datetime,
    ) -> None:
        self.runtime, self.order, self.lease, self.generation, self.authority = (
            runtime,
            order,
            lease,
            generation,
            authority,
        )
        self.deadline_at = deadline_at
        self.prefix = "fiscal-source-producer-job-v1:" + work_key
        intent = _Intent(
            order=order,
            installation_digest=sha256_digest(
                runtime.installation.model_dump(mode="json")
            ),
        )
        self.retain(":intent", intent)
        self.invocation: FiscalProducerInvocationV1 | None = None
        self.actor: FiscalClassifierActorV1 | None = None
        self.command: FiscalRecordClassificationCommandV2 | None = None

    def live(self) -> None:
        current = self.runtime._require(
            self.order, self.lease, self.generation, self.deadline_at
        )
        if (
            current.grant != self.authority.grant
            or current.grant_ref != self.authority.grant_ref
            or current.history_heads != self.authority.history_heads
        ):
            raise producer_invalid("producer authority changed during invocation")
        if self.invocation is not None:
            try:
                self.runtime.history.read_epoch(
                    deadline_at=self.deadline_at
                ).require_current_activity(self.invocation.started_at)
            except ValueError as error:
                raise producer_invalid(
                    "producer attempt predates current epoch"
                ) from error

    def retain(
        self,
        suffix: str,
        value: object,
        *,
        role: str = "fiscal-source-producer-job-v1",
        raw: bytes | None = None,
    ) -> ArtifactRefV1:
        payload = canonical_bytes(value) if raw is None else raw
        previous = self.read(suffix)
        if previous is not None and previous != payload:
            raise SnapshotError(
                "FISCAL_SOURCE_PRODUCER_ORDER_REUSED",
                "producer order identity is immutable",
            )
        record = self.runtime.artifacts.put_bytes_with_receipt(
            self.prefix + suffix,
            payload,
            (),
            media_type="application/json",
            publication_budget=partial(_budget, self.deadline_at),
        ).artifact
        return producer_reference(record, role)

    def read(self, suffix: str) -> bytes | None:
        reader = FiscalArtifactRead(
            self.runtime.artifacts, partial(_budget, self.deadline_at)
        )
        record = reader.current(self.prefix + suffix)
        if record is None:
            return None
        return reader.read(record.artifact_id)

    def start(self) -> ArtifactRefV1:
        self.live()
        order_ref = self.retain(
            ":order", self.order, role="fiscal-source-producer-order-v1"
        )
        self.invocation = FiscalProducerInvocationV1(
            order_ref=order_ref,
            attempt_id="source-producer-attempt:" + uuid4().hex,
            executable_digest=self.runtime.installation.executable_digest,
            installation_digest=sha256_digest(
                self.runtime.installation.model_dump(mode="json")
            ),
            deployment_digest=self.order.deployment_digest,
            issuance=self.order.issuance,
            started_at=datetime.now(UTC),
        )
        return self.retain(
            ":attempt:" + self.invocation.attempt_id,
            self.invocation,
            role="fiscal-source-producer-invocation-v1",
        )

    def _sign(
        self,
        suffix: str,
        body: SignedFiscalSourceClassificationV2
        | SignedFiscalSourcePreparationExecutionV2
        | FiscalAccountingRefusalExecutionV1,
        message: bytes,
        invocation_ref: ArtifactRefV1,
    ) -> str:
        self.live()
        if self.read(suffix + ":signing") is not None:
            raise SnapshotError(
                "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE",
                "signing started without a durable exact outcome",
            )
        key = self.runtime._key(self.authority)
        self.retain(
            suffix + ":signing",
            _Signing(
                invocation_ref=invocation_ref,
                message_digest=hashlib.sha256(message).hexdigest(),
            ),
        )
        self.live()
        signature = key.sign(message).hex()
        self.retain(suffix + ":signed", _Outcome(body=body, signature=signature))
        self.live()
        return signature

    def prepare(self) -> ArtifactRefV1:
        existing = self.read(":preparation")
        if existing is not None:
            ref = producer_reference(
                self.runtime.artifacts.get(self.prefix + ":preparation"),
                "fiscal-source-preparation-execution-v2",
            )
            signed = read_source_preparation(
                FiscalArtifactRead(
                    self.runtime.artifacts, partial(_budget, self.deadline_at)
                ),
                ref,
            )
            self.invocation = FiscalProducerInvocationV1.model_validate_json(
                read_retained_artifact(
                    FiscalArtifactRead(
                        self.runtime.artifacts, partial(_budget, self.deadline_at)
                    ),
                    signed.preparation.invocation_ref,
                )
            )
            self._verify_preparation(signed)
            return ref
        durable = self.read(":preparation-signature:signed")
        if durable is not None:
            body = _Outcome.model_validate_json(durable)
            if not isinstance(body.body, SignedFiscalSourcePreparationExecutionV2):
                raise producer_invalid("preparation recovery version differs")
            signed = body.body.model_copy(update={"signature": body.signature})
            self.invocation = FiscalProducerInvocationV1.model_validate_json(
                read_retained_artifact(
                    FiscalArtifactRead(
                        self.runtime.artifacts, partial(_budget, self.deadline_at)
                    ),
                    signed.preparation.invocation_ref,
                )
            )
            self._verify_preparation(signed)
            return self.retain(
                ":preparation", signed, role="fiscal-source-preparation-execution-v2"
            )
        if self.read(":preparation-signature:signing") is not None:
            raise SnapshotError(
                "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE",
                "preparation signing outcome is unknown",
            )
        invocation_ref = self.start()
        if self.order.source_request is None or self.invocation is None:
            raise producer_invalid("source preparer requires a source-only request")
        evidence, publication = self.runtime.sources.execute(
            self.order.source_request, deadline_at=self.deadline_at
        )
        replay = self.runtime.sources.read_with_metadata(
            evidence.artifact_id, deadline_at=self.deadline_at
        )
        if replay.evidence != evidence or not isinstance(
            evidence.outcome, FiscalValidationCompleteRefusedV1
        ):
            raise producer_invalid(
                "preparation requires exact replayed raw-refused source"
            )
        source_ref = producer_reference(
            publication.artifact, "fiscal-original-validation"
        )
        consumed = tuple(
            producer_reference(record, "fiscal-source-dependency-v1")
            for _, record in replay.records
            if record is not None and record.artifact_id != source_ref.artifact_id
        ) + (source_ref,)
        content_refs = source_content_references(evidence)
        for ref in content_refs:
            raw_content = self.runtime.content.get(
                ref.content_hash, media_type=ref.media_type
            )
            if hashlib.sha256(raw_content).hexdigest() != ref.content_hash:
                raise producer_invalid(
                    "source content differs from exact retained hash"
                )
            self.runtime.artifacts.put_bytes_with_receipt(
                ref.artifact_id,
                raw_content,
                (),
                media_type=ref.media_type,
                publication_budget=partial(_budget, self.deadline_at),
            )
        identity = self.authority.grant.identity
        execution = FiscalSourcePreparationExecutionV1(
            source_validation_ref=source_ref,
            source_binding_digest=sha256_digest(evidence.model_dump(mode="json")),
            runtime=evidence.outcome.runtime,
            authority_id=identity.authority_id,
            authority_grant_ref=self.authority.grant_ref,
            principal_id=identity.principal_id,
            principal_kind=identity.principal_kind,
            key_id=identity.key_id,
            execution_id=self.invocation.attempt_id,
            issuance=self.order.issuance,
            started_at=self.invocation.started_at,
            completed_at=datetime.now(UTC),
        )
        signed = SignedFiscalSourcePreparationExecutionV2(
            preparation=FiscalSourcePreparationExecutionV2(
                execution=execution,
                invocation_ref=invocation_ref,
                request=self.order.source_request,
                mode="captured_then_replayed"
                if publication.wrote
                else "retained_then_replayed",
                consumed_refs=consumed,
                source_content_refs=content_refs,
            ),
            signature="0" * 128,
        )
        signature = self._sign(
            ":preparation-signature", signed, signed.signing_bytes(), invocation_ref
        )
        signed = signed.model_copy(update={"signature": signature})
        self._verify_preparation(signed)
        return self.retain(
            ":preparation", signed, role="fiscal-source-preparation-execution-v2"
        )

    def _verify_preparation(
        self, signed: SignedFiscalSourcePreparationExecutionV2
    ) -> None:
        self.live()
        execution = signed.preparation.execution
        if (
            execution.issuance != self.order.issuance
            or signed.preparation.request != self.order.source_request
            or execution.authority_grant_ref != self.authority.grant_ref
            or not self.order.valid_from
            <= execution.started_at
            <= execution.completed_at
            < self.order.expires_at
        ):
            raise producer_invalid(
                "recovered preparation differs from exact job or expiry"
            )
        self.runtime._key(self.authority).public_key().verify(
            bytes.fromhex(signed.signature), signed.signing_bytes()
        )
        marker_raw = self.read(":preparation-signature:signing")
        if marker_raw is None:
            raise producer_invalid("preparation outcome has no signing marker")
        marker = _Signing.model_validate_json(marker_raw)
        if (
            marker.invocation_ref != signed.preparation.invocation_ref
            or marker.message_digest
            != hashlib.sha256(signed.signing_bytes()).hexdigest()
        ):
            raise producer_invalid("preparation differs from exact signing marker")
        replay = self.runtime.sources.read_with_metadata(
            execution.source_validation_ref.artifact_id, deadline_at=self.deadline_at
        )
        if (
            not isinstance(replay.evidence.outcome, FiscalValidationCompleteRefusedV1)
            or execution.source_binding_digest
            != sha256_digest(replay.evidence.model_dump(mode="json"))
            or execution.runtime != replay.evidence.outcome.runtime
        ):
            raise producer_invalid("source preparation replay changed")
        if (
            source_content_references(replay.evidence)
            != signed.preparation.source_content_refs
        ):
            raise producer_invalid("source preparation content selection changed")
        reader = FiscalArtifactRead(
            self.runtime.artifacts, partial(_budget, self.deadline_at)
        )
        for content_ref in signed.preparation.source_content_refs:
            read_source_content(reader, replay.evidence, content_ref)
        reader.check_current()

    def classify(self) -> FiscalClassificationPublicationV2 | ArtifactRefV1:
        if (
            self.order.preparation_ref is None
            or self.order.witness_ref is None
            or self.runtime.classification_sources is None
            or self.runtime.installation.accreditation_file is None
        ):
            raise producer_invalid(
                "classifier source and policy deployment are required"
            )
        provider = public_accounting_accreditation_provider(
            self.runtime.installation.accreditation_file,
            owner=self.runtime.installation.deployment_uid,
        )
        reader = FiscalArtifactRead(
            self.runtime.artifacts, partial(_budget, self.deadline_at)
        )
        preparation = read_source_preparation(reader, self.order.preparation_ref)
        source = self.runtime.classification_sources.resolve(
            preparation.preparation.execution.source_validation_ref,
            self.order.witness_ref,
            self.order.security_id,
            reader=reader,
            check_deadline=partial(_budget, self.deadline_at),
            deadline_at=self.deadline_at,
        )
        preparer_execution = preparation.preparation.execution
        preparer_authority = self.runtime.authorities.read_current(
            preparer_execution.authority_id,
            expected_role="source_preparer",
            deadline_at=self.deadline_at,
        )
        if (
            preparer_execution.authority_grant_ref != preparer_authority.grant_ref
            or preparer_execution.principal_id
            != preparer_authority.grant.identity.principal_id
            or preparer_execution.key_id != preparer_authority.grant.identity.key_id
            or preparer_execution.issuance != self.order.issuance
            or len(
                {
                    preparer_execution.principal_id,
                    source.witness.principal_id,
                    self.authority.grant.identity.principal_id,
                }
            )
            != 3
            or len(
                {
                    preparer_execution.key_id,
                    source.witness.key_id,
                    self.authority.grant.identity.key_id,
                }
            )
            != 3
        ):
            raise producer_invalid(
                "classifier requires independent current preparation and focus"
            )
        _public_signature(
            preparation.signing_bytes(), preparation.signature, preparer_authority
        )
        self.runtime.history.read_epoch(
            deadline_at=self.deadline_at
        ).require_current_activity(
            preparer_execution.started_at, preparer_execution.completed_at
        )
        accreditation_ref = provider()
        accreditation_raw = read_retained_artifact(reader, accreditation_ref)
        accreditation = FiscalAccountingAccreditationV1.model_validate_json(
            accreditation_raw
        )
        if (
            accreditation.classifier_executable_digest
            != self.runtime.installation.executable_digest
            or canonical_bytes(accreditation) != accreditation_raw
            or accreditation.policy != source_accounting_policy_identity()
            or not accreditation.valid_from
            <= datetime.now(UTC)
            < self.order.expires_at
            <= accreditation.valid_until
        ):
            raise producer_invalid("classifier executable lacks exact accreditation")
        read_retained_artifact(reader, accreditation.independent_review_ref)
        refusal = self.read(":refusal")
        negative_outcome = self.read(":negative:signed")
        if refusal is None and negative_outcome is not None:
            outcome = _Outcome.model_validate_json(negative_outcome)
            if not isinstance(outcome.body, FiscalAccountingRefusalExecutionV1):
                raise producer_invalid("accounting refusal recovery version differs")
            negative = outcome.body.model_copy(update={"signature": outcome.signature})
            marker_raw = self.read(":negative:signing")
            if (
                marker_raw is None
                or _Signing.model_validate_json(marker_raw).message_digest
                != hashlib.sha256(negative.signing_bytes()).hexdigest()
            ):
                raise producer_invalid("accounting refusal recovery marker differs")
            self.retain(
                ":refusal", negative, role="fiscal-accounting-refusal-execution-v1"
            )
            refusal = canonical_bytes(negative)
        if refusal is None and self.read(":negative:signing") is not None:
            raise SnapshotError(
                "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE",
                "accounting refusal signing outcome is unknown",
            )
        if refusal is not None:
            negative = FiscalAccountingRefusalExecutionV1.model_validate_json(refusal)
            if (
                canonical_bytes(negative) != refusal
                or negative.accreditation_ref != accreditation_ref
                or negative.preparation_ref != self.order.preparation_ref
                or negative.classifier_grant_ref != self.authority.grant_ref
            ):
                raise producer_invalid(
                    "retained accounting refusal differs from exact job"
                )
            _public_signature(
                negative.signing_bytes(), negative.signature, self.authority
            )
            record = read_accounting_record(
                read_retained_artifact(reader, negative.accounting_basis_ref),
                check_deadline=partial(_budget, self.deadline_at),
            )
            if (
                record.review() is not None
                or record.result.policy != accreditation.policy
                or record.result.source_evidence_sha256
                != sha256_digest(source.evidence.model_dump(mode="json"))
                or record.result.witness_sha256 != sha256_digest(source.witness)
                or record.result.scope_sha256 != source.scope.scope_digest
            ):
                raise producer_invalid("accounting refusal basis differs")
            self.invocation, retained_order = read_producer_invocation(
                reader, negative.invocation_ref, role="classifier"
            )
            if (
                retained_order != self.order
                or not self.invocation.started_at
                <= negative.completed_at
                < self.order.expires_at
            ):
                raise producer_invalid("accounting refusal invocation or time differs")
            self.live()
            reader.check_current()
            return producer_reference(
                self.runtime.artifacts.get(self.prefix + ":refusal"),
                "fiscal-accounting-refusal-execution-v1",
            )
        completed = self.read(":completed")
        if completed is None:
            if self.read(":classification:signing") is not None:
                raise SnapshotError(
                    "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE",
                    "classifier signing outcome is unknown",
                )
            invocation_ref = self.start()
            invocation = self.invocation
            if invocation is None:
                raise producer_invalid("classifier invocation did not start")
            live = evaluate_source_accounting(
                source, check_deadline=partial(_budget, self.deadline_at)
            )
            basis_raw = encode_accounting_record(
                live, check_deadline=partial(_budget, self.deadline_at)
            )
            basis_ref = self.retain(
                ":basis:" + invocation.attempt_id,
                None,
                role="fiscal-accounting-replay-v3",
                raw=basis_raw,
            )
            review = live.review()
            if review is None:
                negative = FiscalAccountingRefusalExecutionV1(
                    invocation_ref=invocation_ref,
                    accreditation_ref=accreditation_ref,
                    accounting_basis_ref=basis_ref,
                    preparation_ref=self.order.preparation_ref,
                    classifier_grant_ref=self.authority.grant_ref,
                    completed_at=datetime.now(UTC),
                    signature="0" * 128,
                )
                signature = self._sign(
                    ":negative", negative, negative.signing_bytes(), invocation_ref
                )
                return self.retain(
                    ":refusal",
                    negative.model_copy(update={"signature": signature}),
                    role="fiscal-accounting-refusal-execution-v1",
                )
            review_ref = self.retain(
                ":review:" + invocation.attempt_id,
                review,
                role="fiscal-source-accounting-review-v1",
            )
            self.command = FiscalRecordClassificationCommandV2(
                command_id=self.order.order_id,
                authority_id=self.order.authority_id,
                source_validation_ref=source.scope.source_validation_ref,
                witness_ref=self.order.witness_ref,
                review_ref=review_ref,
                preparer_execution_ref=self.order.preparation_ref,
                security_id=self.order.security_id,
                expires_at=self.order.expires_at,
            )
            identity = self.authority.grant.identity
            execution = FiscalClassifierReviewExecutionV1(
                authority_id=identity.authority_id,
                principal_id=identity.principal_id,
                principal_kind=identity.principal_kind,
                key_id=identity.key_id,
                execution_id=invocation.attempt_id,
                issuance=self.order.issuance,
                command_digest=self.command.command_digest,
                scope_digest=source.scope.scope_digest,
                review_ref=review_ref,
                started_at=invocation.started_at,
                completed_at=datetime.now(UTC),
            )
            proof = FiscalClassifierReviewExecutionV2(
                execution=execution,
                invocation_ref=invocation_ref,
                accreditation_ref=accreditation_ref,
                accounting_basis_ref=basis_ref,
                preparation_ref=self.order.preparation_ref,
                classifier_grant_ref=self.authority.grant_ref,
            )
            execution_ref = self.retain(
                ":execution:" + invocation.attempt_id,
                proof,
                role="fiscal-classifier-review-execution-v2",
            )
            self.actor = FiscalClassifierActorV1(
                authority_id=identity.authority_id,
                principal_id=identity.principal_id,
                principal_kind=identity.principal_kind,
                key_id=identity.key_id,
                execution_ref=execution_ref,
            )
            self.retain(
                ":completed", _Completed(command=self.command, actor=self.actor)
            )
        else:
            parsed = _Completed.model_validate_json(completed)
            self.command, self.actor = parsed.command, parsed.actor
            proof = FiscalClassifierReviewExecutionV2.model_validate_json(
                read_retained_artifact(reader, self.actor.execution_ref)
            )
            self.invocation = FiscalProducerInvocationV1.model_validate_json(
                read_retained_artifact(reader, proof.invocation_ref)
            )
        reader.check_current()
        self.live()
        owner = FiscalSourceClassificationOwner(
            artifacts=self.runtime.artifacts,
            history=self.runtime.history,
            authorities=self.runtime.authorities,
            sources=self.runtime.classification_sources,
            signer=self,
            recovery=self,
            producer_evidence=FiscalSourceProducerEvidenceVerifier(provider),
            require_production_evidence=True,
        )
        result = owner.record_classification(
            self.command,
            expected_head=self.order.expected_head,
            deadline_at=self.deadline_at,
        )
        if not isinstance(result, FiscalClassificationPublicationV2):
            raise producer_invalid(
                "classifier returned an unsupported publication version"
            )
        return result

    def authenticate(
        self,
        command: ClassificationCommand,
        review: FiscalSourceAccountingReviewV1,
        *,
        issuance: FiscalIssuanceContextV1,
        deadline_at: datetime,
    ) -> FiscalClassifierActorV1:
        self.live()
        if (
            command != self.command
            or issuance != self.order.issuance
            or self.actor is None
            or deadline_at != self.deadline_at
        ):
            raise producer_invalid("classifier signer only accepts its completed job")
        retained_review = FiscalSourceAccountingReviewV1.model_validate_json(
            read_retained_artifact(
                FiscalArtifactRead(
                    self.runtime.artifacts, partial(_budget, self.deadline_at)
                ),
                command.review_ref,
            )
        )
        if retained_review != review:
            raise producer_invalid(
                "classifier signer review differs from completed job"
            )
        return self.actor

    def _envelope(self, signed: SignedFiscalSourceClassificationV2) -> None:
        reader = FiscalArtifactRead(
            self.runtime.artifacts, partial(_budget, self.deadline_at)
        )
        retained_review = FiscalSourceAccountingReviewV1.model_validate_json(
            read_retained_artifact(reader, signed.command.review_ref)
        )
        proof = FiscalClassifierReviewExecutionV2.model_validate_json(
            read_retained_artifact(reader, signed.reviewer.execution_ref)
        )
        if (
            signed.command != self.command
            or signed.reviewer != self.actor
            or signed.issuance != self.order.issuance
            or signed.authority_grant_ref != self.authority.grant_ref
            or self.invocation is None
            or not self.invocation.started_at <= signed.signed_at <= datetime.now(UTC)
            or signed.command.expires_at != self.order.expires_at
            or signed.review != retained_review
            or proof.execution.completed_at > signed.signed_at
        ):
            raise producer_invalid(
                "classifier signer requires its exact owner envelope"
            )

    def restore(
        self,
        command: ClassificationCommand,
        *,
        actor: FiscalClassifierActorV1,
        issuance: FiscalIssuanceContextV1,
        deadline_at: datetime,
    ) -> SignedClassification | None:
        review = FiscalSourceAccountingReviewV1.model_validate_json(
            read_retained_artifact(
                FiscalArtifactRead(
                    self.runtime.artifacts, partial(_budget, self.deadline_at)
                ),
                command.review_ref,
            )
        )
        self.authenticate(command, review, issuance=issuance, deadline_at=deadline_at)
        if actor != self.actor:
            raise producer_invalid("classifier recovery actor differs")
        raw = self.read(":classification:signed")
        if raw is None:
            if self.read(":classification:signing") is not None:
                raise SnapshotError(
                    "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE",
                    "classification signing outcome is unknown",
                )
            return None
        body = _Outcome.model_validate_json(raw)
        if not isinstance(body.body, SignedFiscalSourceClassificationV2):
            raise producer_invalid("classification recovery version differs")
        signed = body.body.model_copy(update={"signature": body.signature})
        marker = self.read(":classification:signing")
        if (
            marker is None
            or _Signing.model_validate_json(marker).message_digest
            != hashlib.sha256(signed.signing_bytes()).hexdigest()
        ):
            raise producer_invalid(
                "classifier recovered outcome lacks its exact signing marker"
            )
        self._envelope(signed)
        return signed

    def sign(
        self, message: bytes, *, actor: FiscalClassifierActorV1, deadline_at: datetime
    ) -> str:
        if actor != self.actor or deadline_at != self.deadline_at:
            raise producer_invalid("classifier signing actor differs")
        if not message.endswith(b"}"):
            raise producer_invalid("classifier envelope must be an object")
        signed = SignedFiscalSourceClassificationV2.model_validate_json(
            message[:-1] + b',"signature":"' + b"0" * 128 + b'"}'
        )
        if signed.signing_bytes() != message:
            raise producer_invalid("classifier envelope is not canonical")
        self._envelope(signed)
        proof = FiscalClassifierReviewExecutionV2.model_validate_json(
            read_retained_artifact(
                FiscalArtifactRead(
                    self.runtime.artifacts, partial(_budget, self.deadline_at)
                ),
                actor.execution_ref,
            )
        )
        return self._sign(":classification", signed, message, proof.invocation_ref)
