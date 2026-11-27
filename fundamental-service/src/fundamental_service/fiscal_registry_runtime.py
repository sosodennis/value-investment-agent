from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from .contracts import StrictModel
from .content_publication import configured_content_publication_access
from .data_releases import ArtifactRefV1
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    FiscalHistoryHeadV1,
    PostgresFiscalAdmissionHistory,
    ReadOnlyFiscalAdmissionHistory,
)
from .fiscal_authority_contracts import (
    FiscalAuthorityCommandV1,
    FiscalAuthorityDeploymentV1,
    FiscalAuthorityGrantV1,
    FiscalAuthorityPublicationV1,
    FiscalConfiguredRegistryRootV1,
    FiscalGrantAuthorityCommandV1,
    FiscalRegistryExecutionV1,
    FiscalRegistryOperatorV1,
    SignedFiscalAuthorityRecordV1,
    fiscal_authority_command_artifact_id,
    fiscal_authority_command_digest,
)
from .history_recovery_contracts import FiscalIssuanceContextV1
from .metadata import (
    IngestionLockLease,
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    metadata_operation_budget,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

_INSTALLATION = Path("/etc/fundamental/fiscal-registry/installation.json")
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z")


def _refused(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_REGISTRY_REFUSED", message)


def _budget(deadline_at: datetime) -> float:
    now = datetime.now(UTC)
    if deadline_at.utcoffset() is None or deadline_at <= now:
        raise SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED", "registry deadline expired", retryable=True
        )
    return (deadline_at - now).total_seconds()


class _RegistryModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class FiscalRegistryInstallationV1(_RegistryModel):
    protocol: Literal["fundamental.fiscal-registry-installation.v1"] = (
        "fundamental.fiscal-registry-installation.v1"
    )
    audience: str = Field(min_length=1, max_length=256)
    root_id: str = Field(min_length=1, max_length=256)
    workload_uid: int = Field(ge=0)
    deployment_uid: int = Field(ge=0)
    database_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    deployment_file: Path
    orders_directory: Path
    private_key_file: Path
    executable_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FiscalRegistryOrderV1(_RegistryModel):
    protocol: Literal["fundamental.fiscal-registry-order.v1"] = (
        "fundamental.fiscal-registry-order.v1"
    )
    order_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
    audience: str = Field(min_length=1, max_length=256)
    root_id: str = Field(min_length=1, max_length=256)
    deployment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    executable_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuance: FiscalIssuanceContextV1
    command: FiscalAuthorityCommandV1
    expected_head: FiscalHistoryHeadV1 | None
    valid_from: AwareDatetime
    valid_until: AwareDatetime


class _RegistryIntentV1(_RegistryModel):
    protocol: Literal["fundamental.fiscal-registry-job-intent.v1"] = (
        "fundamental.fiscal-registry-job-intent.v1"
    )
    order: FiscalRegistryOrderV1
    installation_digest: str
    execution: FiscalRegistryExecutionV1


class _RegistrySigningV1(_RegistryModel):
    protocol: Literal["fundamental.fiscal-registry-signing-intent.v1"] = (
        "fundamental.fiscal-registry-signing-intent.v1"
    )
    intent_digest: str
    attempt_id: str
    message_digest: str
    started_at: AwareDatetime


def fiscal_registry_executable_digest() -> str:
    root = Path(__file__).parent
    return sha256_digest(
        tuple(
            (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
            for name in (
                "fiscal_registry_runtime.py",
                "fiscal_registry_runner.py",
                "fiscal_admission_authority.py",
                "fiscal_authority_contracts.py",
                "fiscal_admission_history.py",
                "history_recovery_contracts.py",
                "metadata.py",
                "serialization.py",
                "contracts.py",
                "replay.py",
                "snapshots.py",
                "content_publication.py",
            )
        )
    )


def _protected_bytes(
    path: Path, *, owner: int, private: bool = False, limit: int = 16384
) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise _refused("registry deployment path must be absolute")
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
                raise _refused("registry deployment ancestry is not protected")
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
                raise _refused("registry deployment file custody or bounds differ")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                raw = source.read(limit + 1)
            if len(raw) > limit:
                raise _refused("registry deployment file exceeds its byte limit")
            return raw
        finally:
            os.close(descriptor)
    except OSError as error:
        raise _refused("registry deployment file is unavailable or unsafe") from error
    finally:
        os.close(directory)


def load_registry_installation() -> FiscalRegistryInstallationV1:
    raw = _protected_bytes(_INSTALLATION, owner=0)
    try:
        result = FiscalRegistryInstallationV1.model_validate_json(raw)
    except ValueError as error:
        raise _refused("registry installation failed typed decoding") from error
    if raw != canonical_bytes(result.model_dump(mode="json")):
        raise _refused("registry installation is not canonical")
    if result.workload_uid == 0 or result.workload_uid == result.deployment_uid:
        raise _refused("registry workload must be separate from deployment control")
    return result


class FiscalRegistryRuntime:
    def __init__(
        self,
        *,
        installation: FiscalRegistryInstallationV1,
        artifacts: PostgresArtifactStore,
        metadata: PostgresMetadataStore,
        installation_file: Path | None = None,
    ) -> None:
        self._installation_file = installation_file
        self._installation = installation
        self._artifacts = artifacts
        self._metadata = metadata
        self._history = PostgresFiscalAdmissionHistory(metadata)

    def _configuration(self) -> FiscalAuthorityDeploymentV1:
        raw = _protected_bytes(
            self._installation.deployment_file,
            owner=self._installation.deployment_uid,
            limit=1024 * 1024,
        )
        try:
            result = FiscalAuthorityDeploymentV1.model_validate_json(raw)
        except ValueError as error:
            raise _refused("registry roster failed typed decoding") from error
        if raw != canonical_bytes(result):
            raise _refused("registry roster is not canonical")
        return result

    def _order(self, order_id: str) -> FiscalRegistryOrderV1:
        if _ID.fullmatch(order_id) is None:
            raise _refused("registry order identifier is invalid")
        raw = _protected_bytes(
            self._installation.orders_directory / (order_id + ".json"),
            owner=self._installation.deployment_uid,
        )
        try:
            order = FiscalRegistryOrderV1.model_validate_json(raw)
        except ValueError as error:
            raise _refused("registry order failed typed decoding") from error
        if canonical_bytes(order) != raw or order.order_id != order_id:
            raise _refused("registry order identity or canonical bytes differ")
        return order

    def _database_identity(self, deadline_at: datetime) -> None:
        async def inspect(connection: AsyncConnection) -> tuple[str, str]:
            row = (
                await connection.execute(text("SELECT current_user, session_user"))
            ).one()
            return str(row[0]), str(row[1])

        _budget(deadline_at)
        actual = self._metadata.run_fiscal_admission_history(inspect)
        if actual != (
            self._installation.database_role,
            self._installation.database_role,
        ):
            raise _refused("registry workload database identity differs")

    def _require(
        self,
        order: FiscalRegistryOrderV1,
        lease: IngestionLockLease,
        deadline_at: datetime,
    ) -> FiscalConfiguredRegistryRootV1:
        _budget(deadline_at)
        installation = self._installation
        if self._installation_file is not None:
            raw = _protected_bytes(self._installation_file, owner=0)
            if raw != canonical_bytes(installation.model_dump(mode="json")):
                raise _refused("registry installed trust changed")
        if os.getuid() != installation.workload_uid:
            raise _refused("registry workload operating-system identity differs")
        self._database_identity(deadline_at)
        database_now = self._metadata.require_ingestion_lock(lease)
        now = datetime.now(UTC)
        configuration = self._configuration()
        root = next(
            (
                r
                for r in configuration.roots
                if r.identity.root_id == installation.root_id
            ),
            None,
        )
        if (
            self._order(order.order_id) != order
            or order.audience != installation.audience
            or order.root_id != installation.root_id
            or order.deployment_digest != sha256_digest(configuration)
            or order.executable_digest != installation.executable_digest
            or fiscal_registry_executable_digest() != installation.executable_digest
            or root is None
            or root.identity.principal_kind != "machine"
            or not order.valid_from <= now < order.valid_until
            or not order.valid_from <= database_now < order.valid_until
            or not root.identity.valid_from <= now < root.identity.valid_until
            or not root.identity.valid_from <= database_now < root.identity.valid_until
        ):
            raise _refused(
                "registry order, deployment, executable, root or validity differs"
            )
        epoch = self._history.read_epoch(deadline_at=deadline_at)
        try:
            epoch.require_current_issuance(order.issuance)
        except ValueError as error:
            raise _refused(
                "registry order belongs to another issuance epoch"
            ) from error
        stream = "control:fiscal-authority:" + order.command.authority_id
        control = self._history.read_if_present(stream, deadline_at=deadline_at)
        current = control.heads[0] if control is not None else None
        if current != order.expected_head:
            if control is None:
                raise _refused("registry order expected control head differs")
            own = (
                next(
                    (
                        e
                        for e in control.entries
                        if e.event.sequence == current.sequence
                    ),
                    None,
                )
                if current
                else None
            )
            previous = (
                control.entries[-2].event_digest if len(control.entries) > 1 else None
            )
            if (
                own is None
                or own.event.body.kind != "control"
                or own.event.body.command_digest
                != fiscal_authority_command_digest(order.command)
                or own.event.body.payload_ref.artifact_id
                != fiscal_authority_command_artifact_id(order.command)
                or previous
                != (order.expected_head.event_digest if order.expected_head else None)
            ):
                raise _refused("registry order expected control head differs")
        _budget(deadline_at)
        return root

    def apply(
        self, protected_order_id: str, *, deadline_at: datetime
    ) -> FiscalAuthorityPublicationV1:
        with metadata_operation_budget(
            partial(_budget, deadline_at),
            lambda: SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED", "registry deadline expired", retryable=True
            ),
        ):
            _budget(deadline_at)
            order = self._order(protected_order_id)
            work_key = sha256_digest(
                ("fiscal-registry", fiscal_authority_command_artifact_id(order.command))
            )
            lease = self._metadata.try_acquire_ingestion_lock(work_key)
            if lease is None:
                raise SnapshotError(
                    "FISCAL_REGISTRY_IN_FLIGHT",
                    "registry order is already executing",
                    retryable=True,
                )
            try:
                root = self._require(order, lease, deadline_at)
                job = _RegistryJob(self, order, root, lease, work_key, deadline_at)
                owner = FiscalAuthorityOwner(
                    artifacts=self._artifacts,
                    history=self._history,
                    deployment=self._configuration,
                    signer=job,
                    recovery=job,
                )
                if isinstance(order.command, FiscalGrantAuthorityCommandV1):
                    result = owner.grant(
                        order.command,
                        expected_head=order.expected_head,
                        deadline_at=deadline_at,
                    )
                else:
                    if order.expected_head is None:
                        raise _refused(
                            "registry revocation requires an exact control head"
                        )
                    result = owner.revoke(
                        order.command,
                        expected_head=order.expected_head,
                        deadline_at=deadline_at,
                    )
                self._require(order, lease, deadline_at)
                return result
            except ValueError as error:
                raise _refused(
                    "registry retained job evidence failed typed decoding"
                ) from error
            except SQLAlchemyError as error:
                raise SnapshotError(
                    "FISCAL_REGISTRY_STORAGE_FAILED",
                    "registry storage operation failed",
                    retryable=True,
                ) from error
            finally:
                self._metadata.release_ingestion_lock(lease)


class _RegistryJob:
    def __init__(
        self,
        runtime: FiscalRegistryRuntime,
        order: FiscalRegistryOrderV1,
        root: FiscalConfiguredRegistryRootV1,
        lease: IngestionLockLease,
        work_key: str,
        deadline_at: datetime,
    ) -> None:
        self.runtime, self.order, self.root, self.lease = runtime, order, root, lease
        self.prefix = "fiscal-registry-job-v1:" + work_key
        self.attempt = uuid4().hex
        self.intent: _RegistryIntentV1 | None = None
        self.operator: FiscalRegistryOperatorV1 | None = None

    def _read(self, suffix: str) -> bytes | None:
        try:
            record = self.runtime._artifacts.get(self.prefix + suffix)
        except SnapshotError as error:
            if error.code == "ARTIFACT_NOT_FOUND":
                return None
            raise
        raw = self.runtime._artifacts.read(record.artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or hashlib.sha256(raw).hexdigest() != record.content_hash
        ):
            raise _refused("registry job evidence is unavailable or changed")
        return raw

    def _live(self, deadline_at: datetime) -> None:
        if self.runtime._require(self.order, self.lease, deadline_at) != self.root:
            raise _refused("registry signing root changed")
        if self.intent is not None:
            epoch = self.runtime._history.read_epoch(deadline_at=deadline_at)
            try:
                epoch.require_current_activity(self.intent.execution.started_at)
            except ValueError as error:
                raise _refused("registry execution predates current epoch") from error
            if self._read(":intent") != canonical_bytes(self.intent):
                raise _refused("registry job intent changed")

    def authenticate(
        self,
        command: FiscalAuthorityCommandV1,
        *,
        issuance: FiscalIssuanceContextV1,
        deadline_at: datetime,
    ) -> FiscalRegistryOperatorV1:
        self._live(deadline_at)
        if command != self.order.command or issuance != self.order.issuance:
            raise _refused("registry invocation differs from protected order")
        identity = self.root.identity
        raw = self._read(":intent")
        if raw is None:
            execution = FiscalRegistryExecutionV1(
                root_id=identity.root_id,
                principal_id=identity.principal_id,
                principal_kind=identity.principal_kind,
                key_id=identity.key_id,
                execution_id=self.prefix + ":execution",
                operation=command.kind,
                command_digest=fiscal_authority_command_digest(command),
                issuance=issuance,
                started_at=datetime.now(UTC),
            )
            intent = _RegistryIntentV1(
                order=self.order,
                installation_digest=sha256_digest(
                    self.runtime._installation.model_dump(mode="json")
                ),
                execution=execution,
            )
            self.runtime._artifacts.put_with_receipt(
                self.prefix + ":intent",
                intent,
                publication_budget=partial(_budget, deadline_at),
            )
        else:
            intent = _RegistryIntentV1.model_validate_json(raw)
            if (
                raw != canonical_bytes(intent)
                or intent.order != self.order
                or intent.installation_digest
                != sha256_digest(self.runtime._installation.model_dump(mode="json"))
            ):
                raise _refused(
                    "registry command identity was already used with different inputs"
                )
        self.intent = intent
        self._live(deadline_at)
        publication = self.runtime._artifacts.put_with_receipt(
            intent.execution.execution_id,
            intent.execution,
            (sha256_digest(intent),),
            publication_budget=partial(_budget, deadline_at),
        )
        self.operator = FiscalRegistryOperatorV1(
            root_id=identity.root_id,
            principal_id=identity.principal_id,
            principal_kind=identity.principal_kind,
            key_id=identity.key_id,
            execution_ref=ArtifactRefV1(
                role="fiscal-registry-execution-v1",
                artifact_id=publication.artifact.artifact_id,
                content_hash=publication.artifact.content_hash,
                media_type="application/json",
            ),
        )
        return self.operator

    def restore(
        self,
        command: FiscalAuthorityCommandV1,
        *,
        operator: FiscalRegistryOperatorV1,
        issuance: FiscalIssuanceContextV1,
        deadline_at: datetime,
    ) -> SignedFiscalAuthorityRecordV1 | None:
        self._live(deadline_at)
        if (
            command != self.order.command
            or operator != self.operator
            or issuance != self.order.issuance
        ):
            raise _refused("registry recovery invocation differs")
        raw = self._read(":signed")
        if raw is None:
            if self._read(":signing") is not None:
                raise SnapshotError(
                    "FISCAL_REGISTRY_SIGNING_OUTCOME_UNAVAILABLE",
                    "signing started without a durable exact outcome",
                )
            return None
        signed = SignedFiscalAuthorityRecordV1.model_validate_json(raw)
        if raw != canonical_bytes(signed):
            raise _refused("registry recovered envelope is not canonical")
        self._envelope(signed, operator)
        marker_raw = self._read(":signing")
        if marker_raw is None:
            raise _refused("registry signed outcome has no signing intent")
        marker = _RegistrySigningV1.model_validate_json(marker_raw)
        if (
            marker_raw != canonical_bytes(marker)
            or marker.intent_digest != sha256_digest(self.intent)
            or marker.message_digest
            != hashlib.sha256(signed.signing_bytes()).hexdigest()
        ):
            raise _refused("registry signed outcome differs from its signing intent")
        return signed

    def _envelope(
        self, signed: SignedFiscalAuthorityRecordV1, operator: FiscalRegistryOperatorV1
    ) -> None:
        now = datetime.now(UTC)
        if (
            self.intent is None
            or signed.record.command != self.order.command
            or signed.issuer != operator
            or operator != self.operator
            or signed.issuance != self.order.issuance
            or signed.root_evidence_ref != self.root.evidence_ref
            or not self.intent.execution.started_at <= signed.signed_at <= now
            or not self.order.valid_from <= signed.signed_at < self.order.valid_until
        ):
            raise _refused("registry signer only accepts its exact job envelope")
        if isinstance(signed.record, FiscalAuthorityGrantV1):
            target = next(
                (
                    a
                    for a in self.runtime._configuration().authorities
                    if a.identity.authority_id == self.order.command.authority_id
                ),
                None,
            )
            if (
                target is None
                or signed.record.identity != target.identity
                or signed.record.provisioning_ref != target.provisioning_ref
                or not now < signed.record.valid_until
            ):
                raise _refused(
                    "registry grant envelope differs from protected roster or expiry"
                )

    def sign(
        self,
        message: bytes,
        *,
        operator: FiscalRegistryOperatorV1,
        deadline_at: datetime,
    ) -> str:
        self._live(deadline_at)
        try:
            body = json.loads(message)
            body["signature"] = "0" * 128
            signed = SignedFiscalAuthorityRecordV1.model_validate_json(
                canonical_bytes(body)
            )
        except (ValueError, TypeError) as error:
            raise _refused("registry signer requires an authority envelope") from error
        if signed.signing_bytes() != message:
            raise _refused("registry signing envelope must be canonical")
        self._envelope(signed, operator)
        raw = _protected_bytes(
            self.runtime._installation.private_key_file,
            owner=self.runtime._installation.workload_uid,
            private=True,
        )
        try:
            key = serialization.load_pem_private_key(raw, password=None)
        except (ValueError, TypeError) as error:
            raise _refused("registry deployment key is invalid") from error
        if (
            not isinstance(key, Ed25519PrivateKey)
            or hashlib.sha256(
                key.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                )
            ).hexdigest()
            != self.root.identity.key_id
        ):
            raise _refused("registry private key differs from installed root")
        marker = _RegistrySigningV1(
            intent_digest=sha256_digest(self.intent),
            attempt_id=self.attempt,
            message_digest=hashlib.sha256(message).hexdigest(),
            started_at=datetime.now(UTC),
        )
        publication = self.runtime._artifacts.put_with_receipt(
            self.prefix + ":signing",
            marker,
            publication_budget=partial(_budget, deadline_at),
        )
        if not publication.wrote:
            raise SnapshotError(
                "FISCAL_REGISTRY_SIGNING_OUTCOME_UNAVAILABLE",
                "registry signing intent already exists",
            )
        self._live(deadline_at)
        signature = key.sign(message).hex()
        signed = signed.model_copy(update={"signature": signature})
        self.runtime._artifacts.put_with_receipt(
            self.prefix + ":signed",
            signed,
            (sha256_digest(marker),),
            publication_budget=partial(_budget, deadline_at),
        )
        self._live(deadline_at)
        return signature


def build_fiscal_registry_reader(
    *,
    deployment_file: Path,
    deployment_uid: int,
    artifacts: PostgresArtifactStore,
    metadata: PostgresMetadataStore,
) -> FiscalAuthorityOwner:
    def deployment() -> FiscalAuthorityDeploymentV1:
        return FiscalAuthorityDeploymentV1.model_validate_json(
            _protected_bytes(deployment_file, owner=deployment_uid, limit=1024 * 1024)
        )

    return FiscalAuthorityOwner(
        artifacts=artifacts.as_read_only(),
        history=ReadOnlyFiscalAdmissionHistory(
            PostgresFiscalAdmissionHistory(metadata)
        ),
        deployment=deployment,
    )


@contextmanager
def configured_fiscal_registry_runtime() -> Iterator[FiscalRegistryRuntime]:
    installation = load_registry_installation()
    database_url = os.getenv("FUNDAMENTAL_SERVICE_DATABASE_URL")
    data_root = os.getenv("FUNDAMENTAL_SERVICE_DATA_ROOT")
    if not database_url or not data_root:
        raise _refused("registry persistence is not configured")
    metadata = PostgresMetadataStore(database_url, auto_migrate=False)
    try:
        metadata.start_read_only()
        artifacts = PostgresArtifactStore(
            metadata,
            PostgresContentStore(
                Path(data_root) / "content",
                metadata,
                publication_access=configured_content_publication_access(),
            ),
        )
        yield FiscalRegistryRuntime(
            installation=installation,
            artifacts=artifacts,
            metadata=metadata,
            installation_file=_INSTALLATION,
        )
    finally:
        metadata.close()
