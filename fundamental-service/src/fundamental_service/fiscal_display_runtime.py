from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .contracts import StrictModel
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    FiscalHistoryHeadV1,
    PostgresFiscalAdmissionHistory,
    ReadOnlyFiscalAdmissionHistory,
)
from .fiscal_authority_contracts import FiscalAuthorityDeploymentV1
from .fiscal_candidate_contracts import (
    ClassifiedSourceForCandidateV1,
    FiscalStatementCandidateV2,
)
from .fiscal_display_admission import (
    FiscalCandidateReaderPort,
    FiscalDisplayAdmission,
    fiscal_display_executable_digest,
)
from .fiscal_display_contracts import (
    CurrentFiscalDisplay,
    FiscalDisplayRequestV1,
    SignedFiscalDisplayDecisionV1,
)
from .history_recovery_contracts import FiscalIssuanceContextV1
from .metadata import (
    IngestionLockLease,
    PostgresArtifactStore,
    PostgresMetadataStore,
    metadata_operation_budget,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

_INSTALLATION = Path("/etc/fundamental/fiscal-display/installation.json")


def _refused(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_DISPLAY_REFUSED", message)


def _budget(deadline_at: datetime) -> float:
    now = datetime.now(UTC)
    if deadline_at.utcoffset() is None or now >= deadline_at:
        raise SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED", "display deadline expired", retryable=True
        )
    return (deadline_at - now).total_seconds()


class FiscalDisplayInstallationV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-installation.v1"] = (
        "fundamental.fiscal-display-installation.v1"
    )
    audience: str = Field(min_length=1, max_length=256)
    authority_id: str = Field(min_length=1, max_length=256)
    workload_uid: int = Field(ge=0)
    deployment_uid: int = Field(ge=0)
    database_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    deployment_file: Path
    orders_directory: Path
    private_key_file: Path
    executable_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_source_revision: str = Field(min_length=1, max_length=256)
    candidate_authority_id: str = Field(min_length=1, max_length=256)
    mapping_trust_roots_file: Path
    mapping_trust_roots_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    focus_authority_file: Path | None = None
    focus_authority_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_focus_configuration(self) -> FiscalDisplayInstallationV1:
        if (self.focus_authority_file is None) != (self.focus_authority_sha256 is None):
            raise ValueError(
                "installed focus authority requires its exact path and digest"
            )
        return self


class FiscalDisplayOrderV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-order.v1"] = (
        "fundamental.fiscal-display-order.v1"
    )
    order_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
    audience: str
    deployment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    executable_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuance: FiscalIssuanceContextV1
    request: FiscalDisplayRequestV1
    expected_head: FiscalHistoryHeadV1 | None
    valid_from: AwareDatetime
    valid_until: AwareDatetime


def _protected(
    path: Path, *, owner: int, private: bool = False, limit: int = 1024 * 1024
) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise _refused("display deployment paths must be absolute")
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
                raise _refused("display deployment ancestry is not protected")
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
                raise _refused("display file custody or bounds differ")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                raw = source.read(limit + 1)
            if len(raw) > limit:
                raise _refused("display file exceeds byte limit")
            return raw
        finally:
            os.close(descriptor)
    except OSError as error:
        raise _refused("display deployment file is unavailable or unsafe") from error
    finally:
        os.close(directory)


def load_display_installation() -> FiscalDisplayInstallationV1:
    raw = _protected(_INSTALLATION, owner=0)
    result = FiscalDisplayInstallationV1.model_validate_json(raw)
    if (
        raw != canonical_bytes(result.model_dump(mode="json"))
        or result.workload_uid == 0
        or result.workload_uid == result.deployment_uid
    ):
        raise _refused(
            "display installation requires canonical independent workload custody"
        )
    return result


class FiscalDisplayRuntime:
    def __init__(
        self,
        *,
        installation: FiscalDisplayInstallationV1,
        candidates: FiscalCandidateReaderPort,
        artifacts: PostgresArtifactStore,
        metadata: PostgresMetadataStore,
        installation_file: Path | None = None,
    ) -> None:
        self.installation, self.candidates, self.artifacts, self.metadata = (
            installation,
            candidates,
            artifacts,
            metadata,
        )
        self._installation_file = installation_file
        self._read_artifacts = artifacts.as_read_only()
        self.history = PostgresFiscalAdmissionHistory(metadata)

    def configuration(self) -> FiscalAuthorityDeploymentV1:
        raw = _protected(
            self.installation.deployment_file, owner=self.installation.deployment_uid
        )
        result = FiscalAuthorityDeploymentV1.model_validate_json(raw)
        if canonical_bytes(result) != raw:
            raise _refused("display roster is not canonical")
        return result

    def _order(self, identity: str) -> FiscalDisplayOrderV1:
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", identity) is None:
            raise _refused("display order identifier is invalid")
        raw = _protected(
            self.installation.orders_directory / (identity + ".json"),
            owner=self.installation.deployment_uid,
        )
        order = FiscalDisplayOrderV1.model_validate_json(raw)
        if canonical_bytes(order) != raw or order.order_id != identity:
            raise _refused("display order canonical identity differs")
        return order

    def _mapping_configuration(self) -> str:
        digest = hashlib.sha256(
            _protected(
                self.installation.mapping_trust_roots_file,
                owner=self.installation.deployment_uid,
            )
        ).hexdigest()
        if digest != self.installation.mapping_trust_roots_sha256:
            raise _refused("display mapping trust differs from installed identity")
        return digest

    def _require(
        self,
        order: FiscalDisplayOrderV1,
        lease: IngestionLockLease,
        deadline_at: datetime,
    ) -> None:
        _budget(deadline_at)
        self._mapping_configuration()
        installation = self.installation
        if self._installation_file is not None and _protected(
            self._installation_file, owner=0
        ) != canonical_bytes(installation.model_dump(mode="json")):
            raise _refused("display installation changed")
        if os.getuid() != installation.workload_uid:
            raise _refused("display operating-system workload differs")

        async def inspect(connection: AsyncConnection) -> tuple[str, str]:
            row = (
                await connection.execute(text("SELECT current_user, session_user"))
            ).one()
            return str(row[0]), str(row[1])

        if self.metadata.run_fiscal_admission_history(inspect) != (
            installation.database_role,
            installation.database_role,
        ):
            raise _refused("display database workload differs")
        database_now = self.metadata.require_ingestion_lock(lease)
        now = datetime.now(UTC)
        if (
            self._order(order.order_id) != order
            or order.audience != installation.audience
            or order.request.authority_id != installation.authority_id
            or order.deployment_digest != sha256_digest(self.configuration())
            or order.executable_digest != installation.executable_digest
            or fiscal_display_executable_digest() != installation.executable_digest
            or not order.valid_from <= now < order.valid_until
            or not order.valid_from <= database_now < order.valid_until
            or now >= order.request.expires_at
        ):
            raise _refused("display order, role, build, roster or validity differs")
        self.history.read_epoch(deadline_at=deadline_at).require_current_issuance(
            order.issuance
        )
        stream = "control:display-decision:" + order.request.locator_digest
        control = self.history.read_if_present(stream, deadline_at=deadline_at)
        if control is None:
            if order.expected_head is not None:
                raise _refused("display order expected control head differs")
            return
        latest = control.entries[-1].event
        if (
            len(control.entries) != 1
            or latest.body.kind != "control"
            or latest.body.action != "release_approved"
            or latest.origin_id != order.issuance.origin_id
        ):
            raise _refused("display decision was revoked, superseded or imported")
        raw = self._read_artifacts.read(latest.body.payload_ref.artifact_id)
        signed = SignedFiscalDisplayDecisionV1.model_validate_json(raw)
        if signed.body.command.request != order.request:
            raise SnapshotError(
                "FISCAL_DISPLAY_COMMAND_REUSED", "display command identity is immutable"
            )
        if (
            canonical_bytes(signed) != raw
            or hashlib.sha256(raw).hexdigest() != latest.body.payload_ref.content_hash
            or signed.artifact_id
            != order.request.artifact_id("fiscal-display-decision-v1")
            or latest.body.command_digest != signed.body.command.command_digest
            or order.expected_head is not None
            and order.expected_head != control.heads[0]
        ):
            raise _refused(
                "display order expected control head or exact prior outcome differs"
            )

    def apply(
        self, protected_order_id: str, *, deadline_at: datetime
    ) -> CurrentFiscalDisplay:
        with metadata_operation_budget(
            partial(_budget, deadline_at),
            lambda: SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED", "display deadline expired", retryable=True
            ),
        ):
            try:
                order = self._order(protected_order_id)
                lease = self.metadata.try_acquire_ingestion_lock(
                    sha256_digest(("fiscal-display", order.request.command_id))
                )
                if lease is None:
                    raise SnapshotError(
                        "FISCAL_DISPLAY_IN_FLIGHT",
                        "display command is already executing",
                        retryable=True,
                    )
                try:
                    self._require(order, lease, deadline_at)
                    candidate_generation = (
                        self.candidates.current_configuration_digest()
                    )

                    def authorize(
                        request: FiscalDisplayRequestV1, deadline: datetime
                    ) -> Ed25519PrivateKey:
                        self._require(order, lease, deadline)
                        if request != order.request:
                            raise _refused(
                                "display job accepts only its exact protected request"
                            )
                        key = serialization.load_pem_private_key(
                            _protected(
                                self.installation.private_key_file,
                                owner=self.installation.workload_uid,
                                private=True,
                            ),
                            password=None,
                        )
                        if not isinstance(key, Ed25519PrivateKey):
                            raise _refused("display workload requires an Ed25519 key")
                        return key

                    owner = FiscalDisplayAdmission(
                        candidates=self.candidates,
                        artifacts=self.artifacts,
                        read_artifacts=self._read_artifacts,
                        history=self.history,
                        authorities=FiscalAuthorityOwner(
                            artifacts=self._read_artifacts,
                            history=self.history,
                            deployment=self.configuration,
                        ),
                        configuration_digest=lambda request: sha256_digest(
                            (
                                self.candidates.current_configuration_digest(),
                                self.installation.model_dump(mode="json"),
                                self.configuration(),
                                self._mapping_configuration(),
                                self._order(order.order_id),
                                _candidate_configuration_generation(
                                    request,
                                    artifacts=self._read_artifacts,
                                    deployment_uid=self.installation.deployment_uid,
                                    mapping_trust_roots_file=self.installation.mapping_trust_roots_file,
                                    focus_authority_file=self.installation.focus_authority_file,
                                    focus_authority_sha256=self.installation.focus_authority_sha256,
                                ),
                            )
                        ),
                        authorize=authorize,
                    )
                    operation = owner.open_review_and_decide(
                        order.request,
                        expected_head=order.expected_head,
                        deadline_at=deadline_at,
                    )
                    with operation:
                        self._require(order, lease, deadline_at)
                        if (
                            self.candidates.current_configuration_digest()
                            != candidate_generation
                        ):
                            raise _refused(
                                "display candidate configuration changed before return"
                            )
                    return operation.completed
                finally:
                    self.metadata.release_ingestion_lock(lease)
            except ValueError as error:
                raise _refused(
                    "display retained or deployment evidence failed typed validation"
                ) from error


def require_candidate_configuration(installation: FiscalDisplayInstallationV1) -> None:
    from .fiscal_preparation_runtime import FiscalPreparationDeploymentV1

    selected = FiscalPreparationDeploymentV1.from_env(write=False)
    if (
        selected.authority_deployment_file != installation.deployment_file
        or selected.candidate_authority_id != installation.candidate_authority_id
        or selected.mapping_trust_roots_file != installation.mapping_trust_roots_file
    ):
        raise _refused(
            "display candidate configuration differs from installed selectors"
        )
    if (
        hashlib.sha256(
            _protected(
                installation.mapping_trust_roots_file, owner=installation.deployment_uid
            )
        ).hexdigest()
        != installation.mapping_trust_roots_sha256
    ):
        raise _refused("display candidate mapping trust differs from installation")


def _candidate_configuration_generation(
    request: FiscalDisplayRequestV1,
    *,
    artifacts: PostgresArtifactStore,
    deployment_uid: int,
    mapping_trust_roots_file: Path,
    focus_authority_file: Path | None,
    focus_authority_sha256: str | None = None,
) -> str:
    raw = artifacts.read(request.candidate_ref.artifact_id)
    if hashlib.sha256(raw).hexdigest() != request.candidate_ref.content_hash:
        raise _refused("display fixed candidate hash changed")
    candidate = FiscalStatementCandidateV2.model_validate_json(raw)
    mapping = _protected(mapping_trust_roots_file, owner=deployment_uid)
    focus = None
    if any(
        isinstance(use, ClassifiedSourceForCandidateV1)
        for use in candidate.body.content.source_uses
    ):
        if focus_authority_file is None or os.getenv(
            "FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE"
        ) != str(focus_authority_file):
            raise _refused("classified display requires its installed focus authority")
        focus = _protected(focus_authority_file, owner=deployment_uid)
        if (
            focus_authority_sha256 is not None
            and hashlib.sha256(focus).hexdigest() != focus_authority_sha256
        ):
            raise _refused(
                "classified display focus authority differs from installation"
            )
    return sha256_digest(
        (
            hashlib.sha256(mapping).hexdigest(),
            hashlib.sha256(focus).hexdigest() if focus is not None else None,
        )
    )


def build_fiscal_display_reader(
    *,
    candidates: FiscalCandidateReaderPort,
    deployment_file: Path,
    deployment_uid: int,
    mapping_trust_roots_file: Path,
    artifacts: PostgresArtifactStore,
    metadata: PostgresMetadataStore,
    focus_authority_file: Path | None = None,
) -> FiscalDisplayAdmission:
    readonly = artifacts.as_read_only()
    history = ReadOnlyFiscalAdmissionHistory(PostgresFiscalAdmissionHistory(metadata))

    def deployment() -> FiscalAuthorityDeploymentV1:
        return FiscalAuthorityDeploymentV1.model_validate_json(
            _protected(deployment_file, owner=deployment_uid)
        )

    return FiscalDisplayAdmission(
        candidates=candidates,
        artifacts=readonly,
        read_artifacts=readonly,
        history=history,
        authorities=FiscalAuthorityOwner(
            artifacts=readonly, history=history, deployment=deployment
        ),
        configuration_digest=lambda request: sha256_digest(
            (
                candidates.current_configuration_digest(),
                deployment(),
                _candidate_configuration_generation(
                    request,
                    artifacts=readonly,
                    deployment_uid=deployment_uid,
                    mapping_trust_roots_file=mapping_trust_roots_file,
                    focus_authority_file=focus_authority_file,
                ),
            )
        ),
    )
