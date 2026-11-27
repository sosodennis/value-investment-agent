from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Literal
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .automatic_data_release import automatic_release_suite_digest
from .data_releases import (
    ActiveDataReleaseV1,
    DataReleaseActivationCommandV1,
    DataReleaseTrustRootsV1,
    ReleaseModel,
)
from .fiscal_admission_history import (
    PostgresFiscalAdmissionHistory,
    ReadOnlyFiscalAdmissionHistory,
)
from .fiscal_display_admission import FiscalCandidateReaderPort
from .fiscal_display_runtime import build_fiscal_display_reader
from .fiscal_preparation_runtime import (
    FiscalPreparationDeploymentV1,
    FiscalPreparationInputs,
    build_fiscal_candidate_runtime,
    configured_fiscal_candidate_runtime,
)
from .fiscal_release_contracts import (
    FiscalPublishV2,
    FiscalReleaseCandidateReceiptV2,
    FiscalReleaseManifestV2,
)
from .data_releases import ArtifactRefV1
from .fiscal_releases import (
    FiscalReleaseReader,
    FiscalReleaseService,
    FiscalReleaseSigningJob,
    _CompletedFiscalReplay,
)
from .history_recovery_contracts import FiscalIssuanceContextV1
from .metadata import (
    PostgresArtifactStore,
    PostgresMetadataStore,
    PostgresContentStore,
    PostgresSnapshotRepository,
    PostgresCanonicalFactRepository,
    metadata_operation_budget,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .source_acquisition import SecAcquisitionUseCase, SecAcquisitionSettings
from .sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    SecSourceError,
    _SecResponse,
)
from .ingestion import SecIngestionService
from .fiscal_classification_source import FiscalClassificationSourceResolver
from .fiscal_focus_witness import (
    FiscalDiagnosticFocusWitnessOwner,
    FiscalFocusValidatorAuthorityV1,
)
from .fiscal_source_validation import resolve_fiscal_validation_profile
from .fiscal_source_producer_runtime import public_accounting_accreditation_provider
from .fiscal_validation_contracts import FiscalValidationPinV1
from .arelle_parser import ParserResourcePolicy


class FiscalReleaseReadConfigurationV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-read-configuration.v1"] = (
        "fundamental.fiscal-release-read-configuration.v1"
    )
    deployment_uid: int = Field(ge=0)
    deployment_file: Path
    candidate_authority_id: str = Field(min_length=1)
    mapping_trust_roots_file: Path
    release_trust_roots_file: Path
    declared_source_revision: str = Field(min_length=1)
    focus_authority_file: Path | None = None


class FiscalReleaseInstallationV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-installation.v2"] = (
        "fundamental.fiscal-release-installation.v2"
    )
    audience: str = Field(min_length=1)
    reader: FiscalReleaseReadConfigurationV1
    workload_uid: int = Field(ge=0)
    database_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    orders_directory: Path
    private_key_file: Path
    verifier_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    verification_suite_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canary_configuration_file: Path


class FiscalCanaryConfigurationV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-readonly-canary-configuration.v1"] = (
        "fundamental.fiscal-readonly-canary-configuration.v1"
    )
    database_url_file: Path
    database_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    content_root: Path
    source_settings: SecAcquisitionSettings
    sec_request_policy: SecRequestPolicy
    resource_policy: ParserResourcePolicy
    accounting_accreditation_file: Path | None = None


class FiscalReleaseOrderV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-order.v2"] = (
        "fundamental.fiscal-release-order.v2"
    )
    order_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
    audience: str
    installation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuance: FiscalIssuanceContextV1
    approved: FiscalPublishV2
    verification_run_id: str = Field(min_length=1)
    operation: Literal["publish", "activate"] = "publish"
    activation: DataReleaseActivationCommandV1 | None = None
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def exact_operation(self) -> FiscalReleaseOrderV2:
        if (self.operation == "activate") != (
            self.activation is not None
        ) or self.valid_from >= self.valid_until:
            raise ValueError("fiscal release order operation or validity differs")
        return self


def protected_release_file(path: Path, *, owner: int, private: bool = False) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise SnapshotError(
            "FISCAL_RELEASE_CONFIGURATION_INVALID",
            "release deployment paths must be absolute",
        )
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
                raise ValueError("release deployment ancestry is not protected")
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
                or info.st_size > 1024 * 1024
            ):
                raise ValueError("release deployment file is not protected or bounded")
            raw = bytearray()
            while chunk := os.read(descriptor, min(65536, 1024 * 1024 + 1 - len(raw))):
                raw.extend(chunk)
                if len(raw) > 1024 * 1024:
                    raise ValueError("release deployment file exceeds its bound")
            return bytes(raw)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def release_configuration_digest(config: FiscalReleaseReadConfigurationV1) -> str:
    paths = [
        config.deployment_file,
        config.mapping_trust_roots_file,
        config.release_trust_roots_file,
    ]
    if config.focus_authority_file is not None:
        paths.append(config.focus_authority_file)
    return sha256_digest(
        (
            config.model_dump(mode="json"),
            tuple(
                (
                    str(path),
                    hashlib.sha256(
                        protected_release_file(path, owner=config.deployment_uid)
                    ).hexdigest(),
                )
                for path in paths
            ),
        )
    )


def _canary_configuration_digest(
    reader: FiscalReleaseReadConfigurationV1, configuration_file: Path
) -> str:
    return sha256_digest(
        (
            release_configuration_digest(reader),
            hashlib.sha256(
                protected_release_file(configuration_file, owner=reader.deployment_uid)
            ).hexdigest(),
        )
    )


def release_workflow_configuration_digest(
    installation: FiscalReleaseInstallationV2,
) -> str:
    return _canary_configuration_digest(
        installation.reader, installation.canary_configuration_file
    )


@dataclass(frozen=True)
class _FiscalReadonlyCanary:
    reader: FiscalReleaseReadConfigurationV1
    configuration_file: Path
    credential_owner: int
    writer_role: str

    def _replay_candidate_canary(
        self,
        manifest: FiscalReleaseManifestV2,
        checks_ref: ArtifactRefV1,
        *,
        deadline_at: datetime,
    ) -> _CompletedFiscalReplay:
        with _readonly_canary_reader(self, deadline_at=deadline_at) as reader:
            completed = reader._replay_candidate_canary(
                manifest, checks_ref, deadline_at=deadline_at
            )
        return completed


class _RetainedCanaryAdapter(SecEdgarSourceAdapter):
    def _request(
        self, uri: str, *, deadline_at: datetime | None = None
    ) -> _SecResponse:
        raise SecSourceError(
            "SEC_CAPTURE_MISSING",
            "readonly fiscal canary requires retained source closure",
        )


@contextmanager
def _readonly_canary_reader(
    installation: _FiscalReadonlyCanary, *, deadline_at: datetime
) -> Iterator[FiscalReleaseReader]:
    def budget() -> float:
        remaining = (deadline_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED",
                "readonly fiscal canary deadline expired",
                retryable=True,
            )
        return remaining

    budget()
    owner = installation.reader.deployment_uid
    raw = protected_release_file(installation.configuration_file, owner=owner)
    config = FiscalCanaryConfigurationV1.model_validate_json(raw)
    if (
        canonical_bytes(config.model_dump(mode="json")) != raw
        or config.database_role == installation.writer_role
    ):
        raise ValueError("canary requires its own canonical SELECT-only configuration")
    secret = protected_release_file(
        config.database_url_file, owner=installation.credential_owner, private=True
    )
    database_url = secret.decode("utf-8").strip()
    if not database_url or "\n" in database_url or "\r" in database_url:
        raise ValueError("canary database credential is unavailable")
    metadata = PostgresMetadataStore(database_url, auto_migrate=False)
    try:
        with metadata_operation_budget(
            budget,
            lambda: SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED",
                "readonly fiscal canary deadline expired",
                retryable=True,
            ),
        ):
            metadata.start_read_only()
            metadata.require_fiscal_readonly_role(config.database_role)
            content = PostgresContentStore(
                config.content_root, metadata, read_only=True
            )
            artifacts = PostgresArtifactStore(metadata, content, read_only=True)
            adapter = _RetainedCanaryAdapter(config.sec_request_policy)
            ingestion = SecIngestionService(
                source_adapter=adapter,
                content_store=content,
                snapshot_repository=PostgresSnapshotRepository(metadata),
                audit_store=artifacts,
                fact_repository=PostgresCanonicalFactRepository(metadata),
            )
            acquisition = SecAcquisitionUseCase(
                adapter=adapter,
                ingestion=ingestion,
                metadata=metadata,
                content_store=content,
                settings=config.source_settings,
                authorized_organizations=frozenset(),
                capture_store=artifacts,
            )
            discovery = acquisition.fiscal_discovery()
            sources = acquisition.fiscal_source_closure(
                declared_source_revision=installation.reader.declared_source_revision
            )

            def generation() -> str:
                budget()
                if (
                    protected_release_file(installation.configuration_file, owner=owner)
                    != raw
                    or protected_release_file(
                        config.database_url_file,
                        owner=installation.credential_owner,
                        private=True,
                    )
                    != secret
                ):
                    raise ValueError("readonly fiscal canary configuration changed")
                metadata.require_fiscal_readonly_role(config.database_role)
                return _canary_configuration_digest(
                    installation.reader, installation.configuration_file
                )

            def focus_authority() -> FiscalFocusValidatorAuthorityV1:
                if installation.reader.focus_authority_file is None:
                    raise ValueError(
                        "classified canary source requires its focus authority"
                    )
                return FiscalFocusValidatorAuthorityV1.model_validate_json(
                    protected_release_file(
                        installation.reader.focus_authority_file, owner=owner
                    )
                )

            witnesses = FiscalDiagnosticFocusWitnessOwner(
                closure=sources,
                artifacts=artifacts,
                content=content,
                taxonomy_cache_dir=config.source_settings.taxonomy_cache_dir,
                authority=focus_authority,
                private_key=None,
                profile_resolver=partial(
                    resolve_fiscal_validation_profile, acquisition
                ),
                resource_policy=config.resource_policy.validate(),
            )
            resolver = FiscalClassificationSourceResolver(
                sources=sources,
                discovery=discovery,
                witnesses=witnesses,
                content=content,
            )

            def unavailable_accreditation() -> ArtifactRefV1:
                raise SnapshotError(
                    "FISCAL_CANARY_CONFIGURATION_INVALID",
                    "classified canary source requires its public accreditation selector",
                )

            inputs = FiscalPreparationInputs(
                artifacts,
                content,
                discovery,
                sources,
                FiscalValidationPinV1(
                    declared_source_revision=installation.reader.declared_source_revision,
                    taxonomy_manifest_id=config.source_settings.taxonomy_manifest_id,
                ),
                resolver,
                generation,
                public_accounting_accreditation_provider(
                    config.accounting_accreditation_file, owner=owner
                )
                if config.accounting_accreditation_file is not None
                else unavailable_accreditation,
            )
            candidates = build_fiscal_candidate_runtime(
                inputs,
                metadata,
                FiscalPreparationDeploymentV1(
                    authority_deployment_file=installation.reader.deployment_file,
                    candidate_authority_id=installation.reader.candidate_authority_id,
                    mapping_trust_roots_file=installation.reader.mapping_trust_roots_file,
                ),
                write=False,
            )
            reader = build_fiscal_release_reader(
                candidates=candidates,
                artifacts=artifacts,
                metadata=metadata,
                configuration=installation.reader,
            )
            original_generation = reader.configuration_digest
            reader.configuration_digest = lambda: sha256_digest(
                (generation(), original_generation())
            )
            yield reader
            generation()
    finally:
        metadata.close()


def build_fiscal_release_reader(
    *,
    candidates: FiscalCandidateReaderPort,
    artifacts: PostgresArtifactStore,
    metadata: PostgresMetadataStore,
    configuration: FiscalReleaseReadConfigurationV1,
    configuration_file: Path | None = None,
) -> FiscalReleaseReader:
    readonly = artifacts.as_read_only()
    display = build_fiscal_display_reader(
        candidates=candidates,
        deployment_file=configuration.deployment_file,
        deployment_uid=configuration.deployment_uid,
        mapping_trust_roots_file=configuration.mapping_trust_roots_file,
        artifacts=readonly,
        metadata=metadata,
        focus_authority_file=configuration.focus_authority_file,
    )

    def generation() -> str:
        if configuration_file is not None and protected_release_file(
            configuration_file, owner=0
        ) != canonical_bytes(configuration.model_dump(mode="json")):
            raise ValueError("release reader installation changed")
        return sha256_digest(
            (
                release_configuration_digest(configuration),
                candidates.current_configuration_digest(),
            )
        )

    return FiscalReleaseReader(
        display=display,
        artifacts=readonly,
        history=ReadOnlyFiscalAdmissionHistory(
            PostgresFiscalAdmissionHistory(metadata)
        ),
        publications=metadata,
        trust_roots=lambda: DataReleaseTrustRootsV1.model_validate_json(
            protected_release_file(
                configuration.release_trust_roots_file,
                owner=configuration.deployment_uid,
            )
        ),
        configuration_digest=generation,
        read_operation=readonly.scoped_read_operation,
        seal_read_operation=readonly.seal_scoped_read_operation,
        expected_candidate_authority_id=configuration.candidate_authority_id,
    )


def configured_fiscal_release_reader(
    acquisition: SecAcquisitionUseCase,
    metadata: PostgresMetadataStore,
    artifacts: PostgresArtifactStore,
    path: Path,
) -> FiscalReleaseReader:
    configuration = FiscalReleaseReadConfigurationV1.model_validate_json(
        protected_release_file(path, owner=0)
    )
    if canonical_bytes(configuration.model_dump(mode="json")) != protected_release_file(
        path, owner=0
    ):
        raise ValueError("release reader configuration is not canonical")
    selected = FiscalPreparationDeploymentV1.from_env(write=False)
    if (
        selected.authority_deployment_file,
        selected.candidate_authority_id,
        selected.mapping_trust_roots_file,
    ) != (
        configuration.deployment_file,
        configuration.candidate_authority_id,
        configuration.mapping_trust_roots_file,
    ):
        raise ValueError("fiscal release candidate selectors differ from installation")
    candidates = configured_fiscal_candidate_runtime(
        acquisition,
        metadata,
        declared_source_revision=configuration.declared_source_revision,
        write=False,
    )
    return build_fiscal_release_reader(
        candidates=candidates,
        artifacts=artifacts,
        metadata=metadata,
        configuration=configuration,
        configuration_file=path,
    )


class FiscalReleaseRuntime:
    def __init__(
        self,
        *,
        installation: FiscalReleaseInstallationV2,
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
        self.installation_file = installation_file

    def apply(
        self, order_id: str, *, deadline_at: datetime
    ) -> FiscalReleaseCandidateReceiptV2 | ActiveDataReleaseV1:
        installation = self.installation
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", order_id) is None:
            raise ValueError("release order identity is invalid")
        order_path = installation.orders_directory / (order_id + ".json")
        raw = protected_release_file(
            order_path, owner=installation.reader.deployment_uid
        )
        order = FiscalReleaseOrderV2.model_validate_json(raw)
        if canonical_bytes(order) != raw or order.order_id != order_id:
            raise ValueError("release order canonical identity differs")
        history = PostgresFiscalAdmissionHistory(self.metadata)
        lease = self.metadata.try_acquire_ingestion_lock(
            sha256_digest(("fiscal-release", order.approved))
        )
        if lease is None:
            raise SnapshotError(
                "FISCAL_RELEASE_IN_FLIGHT",
                "fiscal publication is already executing",
                retryable=True,
            )
        try:
            candidate_generation = self.candidates.current_configuration_digest()

            def authorize(
                approved: FiscalPublishV2, deadline: datetime
            ) -> Ed25519PrivateKey:
                now = datetime.now(UTC)
                if (
                    deadline.utcoffset() is None
                    or now >= deadline
                    or not order.valid_from <= now < order.valid_until
                ):
                    raise ValueError("fiscal release order or deadline expired")
                if (
                    self.candidates.current_configuration_digest()
                    != candidate_generation
                    or os.getuid() != installation.workload_uid
                    or approved != order.approved
                    or order.audience != installation.audience
                    or order.installation_digest
                    != sha256_digest(installation.model_dump(mode="json"))
                    or order.configuration_digest
                    != release_workflow_configuration_digest(installation)
                ):
                    raise ValueError(
                        "fiscal release installed workload or order binding differs"
                    )
                if (
                    protected_release_file(
                        order_path, owner=installation.reader.deployment_uid
                    )
                    != raw
                ):
                    raise ValueError("fiscal release order changed")
                if self.installation_file is not None and protected_release_file(
                    self.installation_file, owner=0
                ) != canonical_bytes(installation.model_dump(mode="json")):
                    raise ValueError("fiscal release installation changed")
                if (
                    installation.verification_suite_digest
                    != automatic_release_suite_digest()
                ):
                    raise ValueError(
                        "fiscal release workflow suite differs from installed build"
                    )

                async def users(connection: AsyncConnection) -> tuple[str, str]:
                    result = (
                        await connection.execute(
                            text("SELECT current_user, session_user")
                        )
                    ).one()
                    return str(result[0]), str(result[1])

                if self.metadata.run_fiscal_admission_history(users) != (
                    installation.database_role,
                    installation.database_role,
                ):
                    raise ValueError("fiscal release database workload differs")
                epoch = history.read_epoch(deadline_at=deadline)
                epoch.require_current_issuance(order.issuance)
                epoch.require_current_activity(now)
                database_now = self.metadata.require_ingestion_lock(lease)
                if (
                    not order.valid_from
                    <= database_now
                    < min(order.valid_until, deadline)
                ):
                    raise ValueError(
                        "fiscal release workload database validity expired"
                    )
                key = serialization.load_pem_private_key(
                    protected_release_file(
                        installation.private_key_file,
                        owner=installation.workload_uid,
                        private=True,
                    ),
                    password=None,
                )
                if not isinstance(key, Ed25519PrivateKey):
                    raise ValueError("fiscal release workflow requires an Ed25519 key")
                roots = DataReleaseTrustRootsV1.model_validate_json(
                    protected_release_file(
                        installation.reader.release_trust_roots_file,
                        owner=installation.reader.deployment_uid,
                    )
                )
                root = roots.verifiers.get(installation.verifier_id)
                if (
                    root is None
                    or root.workflow_identity != installation.workflow_identity
                    or root.verification_suite_digest
                    != installation.verification_suite_digest
                    or key.public_key().public_bytes_raw() != root.public_key()
                ):
                    raise ValueError(
                        "fiscal release signing workflow differs from deployment trust"
                    )
                return key

            authorize(order.approved, deadline_at)

            def make_reader() -> FiscalReleaseReader:
                return build_fiscal_release_reader(
                    candidates=self.candidates,
                    artifacts=self.artifacts,
                    metadata=self.metadata,
                    configuration=installation.reader,
                )

            reader = make_reader()
            service = FiscalReleaseService(
                reader=reader,
                canary=_FiscalReadonlyCanary(
                    installation.reader,
                    installation.canary_configuration_file,
                    installation.workload_uid,
                    installation.database_role,
                ),
                artifacts=self.artifacts,
                history=history,
                publications=self.metadata,
                signing=FiscalReleaseSigningJob(
                    installation.verifier_id,
                    installation.workflow_identity,
                    installation.verification_suite_digest,
                    installation.source_revision,
                    order.verification_run_id,
                    authorize,
                ),
            )
            result: FiscalReleaseCandidateReceiptV2 | ActiveDataReleaseV1
            if order.activation is not None:
                result = service.activate(order.activation, deadline_at=deadline_at)
                authorize(order.approved, deadline_at)
            else:
                with service.open_publication(
                    order.approved, deadline_at=deadline_at
                ) as receipt:
                    authorize(order.approved, deadline_at)
                    result = receipt.model_copy(deep=True)
            return result
        finally:
            self.metadata.release_ingestion_lock(lease)
