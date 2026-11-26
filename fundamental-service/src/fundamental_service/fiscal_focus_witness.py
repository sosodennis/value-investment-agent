from __future__ import annotations

import base64
import binascii
import hashlib
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Final, Literal, Protocol
from zipfile import BadZipFile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import AwareDatetime, ConfigDict, Field, ValidationError, field_validator

from .arelle_parser import (
    ArelleFindingV1,
    ArelleValidationProfileV1,
    ParserResourcePolicy,
)
from .command_artifacts import EvidenceArtifactStore
from .contracts import SecIntegrityEvidenceV1, StrictModel
from .data_releases import ArtifactRefV1
from .dqc_applicability import DqcFilingContextV1, dqc_applicability_policy_digest
from .fiscal_diagnostic_focus import (
    ArelleActualFocusFactV1,
    FiscalDiagnosticFocusExecutionV1,
    _match_actual_focus,
    run_fiscal_diagnostic_focus,
)
from .fiscal_parser_evidence import (
    FiscalParserRuntimeRead,
    RetainedFiscalAction,
    RetainedFiscalActions,
    read_fiscal_parser_actions,
)
from .fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalSourceClosure,
    FiscalSourceContentRead,
    FiscalSourceRead,
)
from .fiscal_source_contracts import FiscalFilingV1
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
    FiscalValidationRuntimeV1,
)
from .ingestion import read_sec_xbrl_archive
from .inline_xbrl import InlineDocumentSetInputV1
from .metadata import metadata_operation_budget
from .parser_action_contracts import (
    ParserActionInputV3,
    ParserActionDeliveryV2,
)
from .parser_action_identity import ParserBuildChecks, parser_action_input
from .parser_computation import logical_profile
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .sec_capture import SecResponseReceiptV1
from .sec_integrity import extract_referenced_graphics
from .sec_source import SecSourceError
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError

_FOCUS_ROLE: Final = "fiscal-diagnostic-focus-validator-v1"
_FOCUS_CODE = "DQC.US.0015.5970"
_FOCUS_WORKER_VERSION: Final = "official-actual-focus-worker-v1"
_MAX_AUTHORITY_AGE = timedelta(days=30)


class FiscalDiagnosticFocusWorkerPort(Protocol):
    def __call__(
        self,
        filing_path: Path,
        *,
        profile: ArelleValidationProfileV1,
        taxonomy_version: str,
        taxonomy_cache_dir: Path,
        source_content_hash: str,
        deadline_at: datetime,
        resource_policy: ParserResourcePolicy | None = None,
    ) -> FiscalDiagnosticFocusExecutionV1: ...


@dataclass(frozen=True)
class _StagedFiscalAction:
    action: RetainedFiscalAction
    filing_path: Path


class FiscalFocusValidatorAuthorityV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    authority_id: str = Field(min_length=1, max_length=256)
    principal_id: str = Field(min_length=1, max_length=256)
    role: Literal["fiscal-diagnostic-focus-validator-v1"] = _FOCUS_ROLE
    public_key_ed25519_base64: str = Field(min_length=1)
    status: Literal["active", "revoked"] = "active"
    valid_until: AwareDatetime

    @field_validator("public_key_ed25519_base64")
    @classmethod
    def valid_public_key(cls, value: str) -> str:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True))
        except (binascii.Error, ValueError) as error:
            raise ValueError(
                "validator authority requires an Ed25519 public key"
            ) from error
        return value

    @property
    def key_id(self) -> str:
        key = base64.b64decode(self.public_key_ed25519_base64, validate=True)
        return hashlib.sha256(key).hexdigest()

    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(self.public_key_ed25519_base64, validate=True)
        )


class FiscalFocusActionBindingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    representation: Literal["normalized", "archive"]
    request: ParserActionInputV3
    result_ref: ArtifactRefV1
    report_ref: ArtifactRefV1
    delivery_ref: ArtifactRefV1
    delivery: ParserActionDeliveryV2
    report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FiscalDiagnosticFocusSourceBindingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    source_validation_ref: ArtifactRefV1
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    filing: FiscalFilingV1
    cutoff: AwareDatetime
    source_available_at: AwareDatetime
    integrity: SecIntegrityEvidenceV1
    runtime: FiscalValidationRuntimeV1
    source_responses: tuple[SecResponseReceiptV1, ...]
    raw_report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_report_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_report_findings_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_finding: ArelleFindingV1
    actions: tuple[FiscalFocusActionBindingV1, ...] = Field(min_length=1)
    filing_context: DqcFilingContextV1
    worker_version: Literal["official-actual-focus-worker-v1"] = _FOCUS_WORKER_VERSION
    worker_module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    applicability_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def logical_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class FiscalDiagnosticFocusWitnessV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-diagnostic-focus-witness.v1"] = (
        "fundamental.fiscal-diagnostic-focus-witness.v1"
    )
    source_validation_ref: ArtifactRefV1
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    filing: FiscalFilingV1
    cutoff: AwareDatetime
    source_available_at: AwareDatetime
    integrity: SecIntegrityEvidenceV1
    runtime: FiscalValidationRuntimeV1
    source_responses: tuple[SecResponseReceiptV1, ...]
    raw_report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_report_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_report_findings_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_finding: ArelleFindingV1
    actions: tuple[FiscalFocusActionBindingV1, ...] = Field(min_length=1)
    filing_context: DqcFilingContextV1
    actual_focus: ArelleActualFocusFactV1
    worker_version: Literal["official-actual-focus-worker-v1"] = _FOCUS_WORKER_VERSION
    worker_module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    applicability_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def logical_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))

    @property
    def source_binding_digest(self) -> str:
        binding = FiscalDiagnosticFocusSourceBindingV1.model_validate(
            self.model_dump(mode="python", exclude={"protocol", "actual_focus"})
        )
        return binding.logical_digest

    @classmethod
    def from_binding(
        cls,
        binding: FiscalDiagnosticFocusSourceBindingV1,
        actual_focus: ArelleActualFocusFactV1,
    ) -> FiscalDiagnosticFocusWitnessV1:
        return cls(**binding.model_dump(mode="python"), actual_focus=actual_focus)


class SignedFiscalDiagnosticFocusWitnessV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.signed-fiscal-diagnostic-focus-witness.v1"] = (
        "fundamental.signed-fiscal-diagnostic-focus-witness.v1"
    )
    witness: FiscalDiagnosticFocusWitnessV1
    authority_id: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)
    role: Literal["fiscal-diagnostic-focus-validator-v1"] = _FOCUS_ROLE
    key_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    signed_at: AwareDatetime
    expires_at: AwareDatetime
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))

    @property
    def artifact_id(self) -> str:
        return (
            "fiscal-diagnostic-focus-witness-v1:"
            f"{self.witness.source_binding_digest}:{self.key_id}"
        )


class FiscalDiagnosticFocusWitnessPublicationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    witness: SignedFiscalDiagnosticFocusWitnessV1
    publication: ArtifactPublicationV1


def _witness_dependency_hashes(
    witness: FiscalDiagnosticFocusWitnessV1, key_id: str
) -> tuple[str, ...]:
    integrity = witness.integrity
    return tuple(
        sorted(
            {
                witness.source_validation_ref.content_hash,
                *(item.content_hash for item in witness.source_responses),
                *(
                    ref.content_hash
                    for action in witness.actions
                    for ref in (
                        action.result_ref,
                        action.report_ref,
                        action.delivery_ref,
                    )
                ),
                integrity.raw_content_hash,
                integrity.archive_hash,
                integrity.archive_member_hash,
                integrity.normalized_content_hash,
                integrity.taxonomy_manifest_hash,
                key_id,
            }
        )
    )


class FiscalDiagnosticFocusWitnessOwner:
    """Build and replay source-bound actual-focus witnesses from retained originals."""

    def __init__(
        self,
        *,
        closure: FiscalSourceClosure,
        artifacts: EvidenceArtifactStore,
        content: ContentAddressedStore,
        taxonomy_cache_dir: Path,
        authority: Callable[[], FiscalFocusValidatorAuthorityV1],
        private_key: Callable[[], Ed25519PrivateKey] | None,
        current_time: Callable[[], datetime] = lambda: datetime.now(UTC),
        worker: FiscalDiagnosticFocusWorkerPort = run_fiscal_diagnostic_focus,
        profile_resolver: Callable[[str], ArelleValidationProfileV1] | None = None,
        resource_policy: ParserResourcePolicy | None = None,
        capture_lock: Callable[
            [str, datetime], AbstractContextManager[None]
        ] = lambda _key, _deadline: nullcontext(),
    ) -> None:
        self._closure = closure
        self._artifacts = artifacts
        self._content = content
        self._taxonomy_cache_dir = taxonomy_cache_dir
        self._authority = authority
        self._private_key = private_key
        self._clock = current_time
        self._worker = worker
        self._profile_resolver = profile_resolver
        self._resource_policy = resource_policy
        self._capture_lock = capture_lock

    def execute(
        self, source_ref: ArtifactRefV1, *, deadline_at: datetime
    ) -> FiscalDiagnosticFocusWitnessPublicationV1:
        with metadata_operation_budget(
            partial(self._check_deadline, deadline_at), self._deadline_error
        ):
            return self._execute(source_ref, deadline_at)

    def _execute(
        self, source_ref: ArtifactRefV1, deadline_at: datetime
    ) -> FiscalDiagnosticFocusWitnessPublicationV1:
        reader = FiscalArtifactRead(
            self._artifacts, partial(self._check_deadline, deadline_at)
        )
        self._check_deadline(deadline_at)
        source_ref = self._source_ref(source_ref, reader)
        with self._capture_lock(
            f"fiscal-diagnostic-focus-witness:{source_ref.artifact_id}", deadline_at
        ):
            evidence = self._read_source(source_ref, reader, deadline_at)
            outcome = self._require_refused_focus_source(evidence, source_ref)
            actions = read_fiscal_parser_actions(
                outcome.integrity.validation_evidence,
                relation=outcome.integrity.integrity_relation,
                artifacts=reader,
                build_checks=ParserBuildChecks(),
                delivery_revision=outcome.runtime.delivery_revision,
            )
            profile = self._runtime_profile(outcome)
            binding = self._source_binding(evidence, source_ref, outcome, actions)
            authority = self._current_authority()
            artifact_id = f"fiscal-diagnostic-focus-witness-v1:{binding.logical_digest}:{authority.key_id}"
            existing = self._existing(artifact_id, authority, reader)
            with self._stage_actions(outcome, actions, profile, deadline_at) as staged:
                if existing is not None:
                    self._verify_current_binding(
                        existing, evidence, source_ref, binding
                    )
                else:
                    focus = self._execute_focus(outcome, staged, profile, deadline_at)
            if existing is not None:
                publication = ArtifactPublicationV1(
                    artifact=reader.get(artifact_id), wrote=False
                )
                self._check_current(reader, authority, outcome.runtime, deadline_at)
                self._check_envelope_current(existing, authority)
                return FiscalDiagnosticFocusWitnessPublicationV1(
                    witness=existing, publication=publication
                )
            self._check_current(reader, authority, outcome.runtime, deadline_at)
            witness = FiscalDiagnosticFocusWitnessV1.from_binding(binding, focus)
            signed = self._sign(witness, authority)
            if signed.artifact_id != artifact_id:
                raise SnapshotError(
                    "FISCAL_FOCUS_WITNESS_IDENTITY_INVALID",
                    "signed witness identity differs from its source binding",
                )
            self._check_current(reader, authority, outcome.runtime, deadline_at)
            publication = self._artifacts.put_with_receipt(
                artifact_id,
                signed.model_dump(mode="json"),
                _witness_dependency_hashes(witness, authority.key_id),
                media_type="application/json",
                publication_budget=partial(
                    self._check_authority, authority, deadline_at
                ),
            )
            reader.expect(artifact_id, publication.artifact)
            stored = self._read_envelope(artifact_id, authority, reader)
            if stored != signed:
                raise SnapshotError(
                    "FISCAL_FOCUS_WITNESS_PUBLICATION_INVALID",
                    "published focus witness differs from its signed value",
                )
            self._check_current(reader, authority, outcome.runtime, deadline_at)
            self._check_envelope_current(stored, authority)
            return FiscalDiagnosticFocusWitnessPublicationV1(
                witness=signed, publication=publication
            )

    def read(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> SignedFiscalDiagnosticFocusWitnessV1:
        with metadata_operation_budget(
            partial(self._check_deadline, deadline_at), self._deadline_error
        ):
            reader = FiscalArtifactRead(
                self._artifacts, partial(self._check_deadline, deadline_at)
            )
            self._check_deadline(deadline_at)
            authority = self._current_authority()
            witness = self._read_envelope(artifact_id, authority, reader)
            source_ref = witness.witness.source_validation_ref
            self._source_ref(source_ref, reader)
            evidence = self._read_source(source_ref, reader, deadline_at)
            outcome = self._require_refused_focus_source(evidence, source_ref)
            actions = read_fiscal_parser_actions(
                outcome.integrity.validation_evidence,
                relation=outcome.integrity.integrity_relation,
                artifacts=reader,
                build_checks=ParserBuildChecks(),
                delivery_revision=outcome.runtime.delivery_revision,
            )
            profile = self._runtime_profile(outcome)
            with self._stage_actions(outcome, actions, profile, deadline_at):
                self._verify_current_binding(
                    witness,
                    evidence,
                    source_ref,
                    self._source_binding(evidence, source_ref, outcome, actions),
                )
            self._check_current(reader, authority, outcome.runtime, deadline_at)
            self._check_envelope_current(witness, authority)
            return witness

    def observe(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> FiscalFocusWitnessRead:
        with metadata_operation_budget(
            partial(self._check_deadline, deadline_at), self._deadline_error
        ):
            artifacts, closure, content_store = (
                self._artifacts,
                self._closure,
                self._content,
            )
            reader = FiscalArtifactRead(
                artifacts, partial(self._check_deadline, deadline_at)
            )
            authority = self._current_authority()
            witness = self._read_envelope(artifact_id, authority, reader)
            source_ref = witness.witness.source_validation_ref
            self._source_ref(source_ref, reader)
            source = closure.observe(source_ref.artifact_id, deadline_at=deadline_at)
            for identity, record in source.records:
                reader.expect(identity, record)
            evidence = source.evidence
            outcome = self._require_refused_focus_source(evidence, source_ref)
            actions = read_fiscal_parser_actions(
                outcome.integrity.validation_evidence,
                relation=outcome.integrity.integrity_relation,
                artifacts=reader,
                build_checks=ParserBuildChecks(),
                delivery_revision=outcome.runtime.delivery_revision,
            )
            content = FiscalSourceContentRead(
                content_store, partial(self._check_deadline, deadline_at)
            )
            runtime = FiscalParserRuntimeRead()
            profile = self._runtime_profile(outcome)
            with self._stage_actions(
                outcome, actions, profile, deadline_at, content=content, runtime=runtime
            ):
                self._verify_current_binding(
                    witness,
                    evidence,
                    source_ref,
                    self._source_binding(evidence, source_ref, outcome, actions),
                )
            self._check_current(reader, authority, outcome.runtime, deadline_at)
            self._check_envelope_current(witness, authority)
            return FiscalFocusWitnessRead(
                self,
                reader,
                source,
                content,
                runtime,
                witness,
                authority.model_copy(deep=True),
                deadline_at,
                artifacts,
                closure,
                content_store,
            )

    def _read_source(
        self,
        source_ref: ArtifactRefV1,
        reader: FiscalArtifactRead,
        deadline_at: datetime,
    ) -> FiscalOriginalValidationEvidenceV1:
        retained = self._closure.read_with_metadata(
            source_ref.artifact_id, deadline_at=deadline_at
        )
        for identity, record in retained.records:
            reader.expect(identity, record)
        return retained.evidence

    def _check_current(
        self,
        reader: FiscalArtifactRead,
        authority: FiscalFocusValidatorAuthorityV1,
        runtime: FiscalValidationRuntimeV1,
        deadline_at: datetime,
    ) -> None:
        self._check_deadline(deadline_at)
        if ParserBuildChecks().current() != runtime.parser_build:
            raise SnapshotError(
                "FISCAL_FOCUS_RUNTIME_CHANGED",
                "focus validator build changed during the operation",
            )
        reader.check_current()
        self._check_authority(authority, deadline_at)

    def _check_authority(
        self, authority: FiscalFocusValidatorAuthorityV1, deadline_at: datetime
    ) -> float:
        self._check_deadline(deadline_at)
        if self._current_authority() != authority:
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_INVALID",
                "focus validator authority changed during the operation",
            )
        return self._check_deadline(deadline_at)

    def _source_ref(
        self, ref: ArtifactRefV1, reader: FiscalArtifactRead
    ) -> ArtifactRefV1:
        if (
            ref.role != "fiscal-original-validation"
            or ref.media_type != "application/json"
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_REF_INVALID",
                "focus witness requires a retained fiscal original reference",
            )
        record = reader.get(ref.artifact_id)
        if (
            record.artifact_id != ref.artifact_id
            or record.content_hash != ref.content_hash
            or record.media_type != ref.media_type
            or record.status != "valid"
            or record.retention != "evidence"
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_REF_INVALID",
                "focus witness source reference differs from retained metadata",
            )
        return ref

    def _require_refused_focus_source(
        self, evidence: FiscalOriginalValidationEvidenceV1, source_ref: ArtifactRefV1
    ) -> FiscalValidationCompleteRefusedV1:
        if evidence.artifact_id != source_ref.artifact_id or not isinstance(
            evidence.outcome, FiscalValidationCompleteRefusedV1
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_NOT_REFUSED",
                "focus witness requires a complete raw-refused fiscal validation",
            )
        outcome = evidence.outcome
        if (
            outcome.claim.metadata_status != "matched"
            or outcome.claim.status != "refused"
            or outcome.integrity.quality_decision != "block"
            or outcome.claim.report.dqc_filing_context is None
            or outcome.claim.report.validation_profile.validation_mode != "sec-efm-dqc"
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_NOT_ELIGIBLE",
                "focus witness requires matched metadata and complete blocked validation",
            )
        return outcome

    def _source_binding(
        self,
        evidence: FiscalOriginalValidationEvidenceV1,
        source_ref: ArtifactRefV1,
        outcome: FiscalValidationCompleteRefusedV1,
        actions: RetainedFiscalActions,
    ) -> FiscalDiagnosticFocusSourceBindingV1:
        report = outcome.claim.report
        context = report.dqc_filing_context
        if context is None:
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_NOT_ELIGIBLE", "DQC context is missing"
            )
        findings = tuple(item for item in report.findings if item.code == _FOCUS_CODE)
        if len(findings) != 1:
            raise SnapshotError(
                "FISCAL_FOCUS_FINDING_AMBIGUOUS", "the target finding is not unique"
            )
        target = findings[0]
        if target.severity != "warning" or target.rule_severity != "error":
            raise SnapshotError(
                "FISCAL_FOCUS_FINDING_INVALID",
                "the raw target finding has changed severity",
            )
        applicability = report.finding_applicability(target)
        if applicability is None or applicability.status != "active":
            raise SnapshotError(
                "FISCAL_FOCUS_FINDING_INVALID", "the target diagnostic is not active"
            )
        if set(report.blocking_finding_codes()) != {_FOCUS_CODE}:
            raise SnapshotError(
                "FISCAL_FOCUS_OTHER_BLOCKING_FINDING",
                "another retained finding blocks the source",
            )
        raw_bytes = canonical_bytes(report.model_dump(mode="json"))
        bindings = tuple(
            self._action_binding(action)
            for action in (actions.normalized, actions.archive)
            if action
        )
        return FiscalDiagnosticFocusSourceBindingV1(
            source_validation_ref=source_ref,
            request_digest=evidence.request.digest,
            filing=outcome.claim.filing,
            cutoff=evidence.request.valuation_timestamp,
            source_available_at=outcome.claim.source.available_at,
            integrity=outcome.integrity,
            runtime=outcome.runtime,
            source_responses=outcome.responses,
            raw_report_digest=hashlib.sha256(raw_bytes).hexdigest(),
            raw_report_fact_digest=outcome.integrity.normalized_fact_digest,
            raw_report_findings_digest=sha256_digest(
                sorted(report.findings, key=sha256_digest)
            ),
            raw_finding=target,
            actions=bindings,
            filing_context=context,
            worker_module_sha256=self._worker_digest(),
            applicability_policy_digest=dqc_applicability_policy_digest(
                context.dqc_version
            ),
        )

    def _action_binding(
        self, action: RetainedFiscalAction
    ) -> FiscalFocusActionBindingV1:
        if not isinstance(action.request, ParserActionInputV3):
            raise SnapshotError(
                "FISCAL_FOCUS_PARSER_ACTION_INVALID",
                "focus witness requires source-bound parser action v3",
            )
        roles = {ref.role: ref for ref in action.refs}
        result_ref = roles.get("sec-parser-action-result-v2")
        report_ref = roles.get("sec-parser-action-report-v1")
        delivery_ref = roles.get("sec-parser-action-delivery-v2")
        if result_ref is None or report_ref is None or delivery_ref is None:
            raise SnapshotError(
                "FISCAL_FOCUS_PARSER_ACTION_INVALID",
                "parser action bindings are incomplete",
            )
        return FiscalFocusActionBindingV1(
            representation=action.request.representation,
            request=action.request,
            result_ref=result_ref,
            report_ref=report_ref,
            delivery_ref=delivery_ref,
            delivery=action.delivery,
            report_digest=action.report.replay_digest(),
        )

    def _execute_focus(
        self,
        outcome: FiscalValidationCompleteRefusedV1,
        staged: tuple[_StagedFiscalAction, ...],
        profile: ArelleValidationProfileV1,
        deadline_at: datetime,
    ) -> ArelleActualFocusFactV1:
        results: list[ArelleActualFocusFactV1] = []
        context = outcome.claim.report.dqc_filing_context
        if context is None:
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_NOT_ELIGIBLE", "DQC context is missing"
            )
        for item in staged:
            action = item.action
            self._check_deadline(deadline_at)
            execution = self._worker(
                item.filing_path,
                profile=profile,
                taxonomy_version=outcome.runtime.taxonomy_version,
                taxonomy_cache_dir=self._taxonomy_cache_dir,
                source_content_hash=action.request.source_content_hash,
                deadline_at=deadline_at,
                resource_policy=self._resource_policy,
            )
            self._check_deadline(deadline_at)
            expected_report = action.report.model_copy(
                update={
                    "validation_evidence": tuple(
                        marker
                        for marker in action.report.validation_evidence
                        if not marker.startswith("sec-parser-action-")
                    )
                }
            )
            results.append(
                _match_actual_focus(expected_report, execution, filing_context=context)
            )
        if not results or any(item != results[0] for item in results[1:]):
            raise SnapshotError(
                "FISCAL_FOCUS_REPRESENTATIONS_DIFFER",
                "retained parser representations identify different focus facts",
            )
        return results[0]

    @contextmanager
    def _stage_actions(
        self,
        outcome: FiscalValidationCompleteRefusedV1,
        actions: RetainedFiscalActions,
        profile: ArelleValidationProfileV1,
        deadline_at: datetime,
        *,
        content: FiscalSourceContentRead | None = None,
        runtime: FiscalParserRuntimeRead | None = None,
    ) -> Iterator[tuple[_StagedFiscalAction, ...]]:
        with ExitStack() as scratch:
            yield self._stage_inputs(
                outcome, actions, profile, deadline_at, scratch, content, runtime
            )

    def _stage_inputs(
        self,
        outcome: FiscalValidationCompleteRefusedV1,
        actions: RetainedFiscalActions,
        profile: ArelleValidationProfileV1,
        deadline_at: datetime,
        scratch: ExitStack,
        content_read: FiscalSourceContentRead | None = None,
        runtime_read: FiscalParserRuntimeRead | None = None,
    ) -> tuple[_StagedFiscalAction, ...]:
        integrity = outcome.integrity
        responses = {item.uri: item for item in outcome.responses}
        primary = responses.get(integrity.primary_document_uri)
        archive_receipt = responses.get(integrity.archive_uri)
        if primary is None or archive_receipt is None:
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_RESPONSE_MISSING",
                "primary or archive receipt is missing",
            )
        read_content = self._read_content if content_read is None else content_read.get
        archive = read_content(
            archive_receipt.content_hash, media_type=archive_receipt.media_type
        )
        document_media = {
            item.uri.rsplit("/", 1)[-1]: item.media_type for item in outcome.responses
        }
        inline_docs = tuple(
            item.document.filename for item in integrity.inline_documents
        )
        actual_actions = tuple(
            action for action in (actions.normalized, actions.archive) if action
        )
        staged: list[_StagedFiscalAction] = []
        for action in actual_actions:
            self._check_deadline(deadline_at)
            request = action.request
            filenames = tuple(name for name, _ in request.files)
            root_resources = tuple(
                name
                for name in filenames
                if len(PurePosixPath(name).parts) == 1
                and name
                not in {integrity.archive_member_name, *inline_docs, "input.ixds.json"}
            )
            try:
                members = read_sec_xbrl_archive(
                    archive,
                    primary_document=integrity.archive_member_name,
                    dts_filenames=root_resources,
                    inline_documents=inline_docs,
                )
            except (SnapshotError, ValueError, BadZipFile) as error:
                raise SnapshotError(
                    "FISCAL_FOCUS_STAGING_INVALID",
                    "retained archive could not rebuild parser inputs",
                ) from error
            files: dict[str, bytes] = dict(members)
            for inline in integrity.inline_documents:
                digest = (
                    inline.document.content_hash
                    if request.representation == "normalized"
                    else inline.archive_member_hash
                )
                media_type = document_media.get(inline.document.filename)
                if media_type is None:
                    raise SnapshotError(
                        "FISCAL_FOCUS_STAGING_INVALID",
                        "inline source media type is missing",
                    )
                files[inline.document.filename] = read_content(
                    digest, media_type=media_type
                )
            if not integrity.inline_documents:
                primary_digest = (
                    integrity.normalized_content_hash
                    if request.representation == "normalized"
                    else integrity.archive_member_hash
                )
                files[integrity.archive_member_name] = read_content(
                    primary_digest, media_type=primary.media_type
                )
            if integrity.inline_documents:
                manifest = InlineDocumentSetInputV1(
                    documents=tuple(
                        item.document for item in integrity.inline_documents
                    )
                )
                files["input.ixds.json"] = canonical_bytes(manifest)
            for filename, content in tuple(files.items()):
                if PurePosixPath(filename).suffix.lower() not in {
                    ".htm",
                    ".html",
                    ".xhtml",
                }:
                    continue
                for graphics_name, graphic in extract_referenced_graphics(
                    html_content=content,
                    archive_content=archive,
                    primary_document=filename,
                ):
                    previous = files.get(graphics_name)
                    if previous is not None and previous != graphic:
                        raise SnapshotError(
                            "FISCAL_FOCUS_STAGING_INVALID",
                            "staged archive resource conflicts",
                        )
                    files[graphics_name] = graphic
            expected = dict(request.files)
            if set(files) != set(expected) or any(
                hashlib.sha256(files[name]).hexdigest() != digest
                for name, digest in expected.items()
            ):
                raise SnapshotError(
                    "FISCAL_FOCUS_STAGING_INVALID",
                    "reconstructed parser files differ from retained action inputs",
                )
            root = Path(
                scratch.enter_context(
                    TemporaryDirectory(prefix="fundamental-fiscal-focus-input-")
                )
            )
            for filename, content in files.items():
                path = root.joinpath(*PurePosixPath(filename).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            filing_path = root.joinpath(*PurePosixPath(request.entrypoint).parts)
            expected_request = parser_action_input(
                filing_path,
                representation=request.representation,
                delivery_revision=outcome.runtime.delivery_revision,
                normalization_inputs=request.normalization_inputs,
                profile=profile,
                taxonomy_version=outcome.runtime.taxonomy_version,
                taxonomy_cache_dir=self._taxonomy_cache_dir,
                source_content_hash=request.source_content_hash,
                build_checks=ParserBuildChecks(),
            )
            if expected_request != request:
                raise SnapshotError(
                    "FISCAL_FOCUS_STAGING_INVALID",
                    "reconstructed parser request differs from retained action",
                )
            if runtime_read is not None:
                if not isinstance(expected_request, ParserActionInputV3):
                    raise SnapshotError(
                        "FISCAL_FOCUS_STAGING_INVALID",
                        "focus parser runtime is incomplete",
                    )
                runtime_read.observe(
                    expected_request,
                    profile,
                    self._taxonomy_cache_dir,
                    outcome.runtime.delivery_revision,
                )
            self._check_deadline(deadline_at)
            staged.append(_StagedFiscalAction(action, filing_path))
        return tuple(staged)

    def _runtime_profile(
        self, outcome: FiscalValidationCompleteRefusedV1
    ) -> ArelleValidationProfileV1:
        if self._profile_resolver is None:
            raise SnapshotError(
                "FISCAL_FOCUS_PROFILE_RESOLVER_UNAVAILABLE",
                "configured fiscal validation profile resolver is required",
            )
        profile = self._profile_resolver(outcome.runtime.dqc_namespace)
        report_profile = outcome.claim.report.validation_profile
        if (
            profile.profile_id != outcome.runtime.validation_profile_id
            or profile.digest() != outcome.runtime.validation_profile_digest
            or logical_profile(profile) != logical_profile(report_profile)
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_PROFILE_MISMATCH",
                "configured fiscal validation profile differs from retained runtime",
            )
        return profile

    def _read_content(self, digest: str, media_type: str) -> bytes:
        value = self._content.get(digest, media_type=media_type)
        if hashlib.sha256(value).hexdigest() != digest:
            raise SnapshotError(
                "FISCAL_FOCUS_STAGING_INVALID", "retained content hash differs"
            )
        return value

    def _sign(
        self,
        witness: FiscalDiagnosticFocusWitnessV1,
        authority: FiscalFocusValidatorAuthorityV1,
    ) -> SignedFiscalDiagnosticFocusWitnessV1:
        now = self._now()
        if self._private_key is None:
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_UNCONFIGURED",
                "focus signing capability is not configured",
            )
        key = self._private_key()
        if (
            key.public_key().public_bytes_raw()
            != authority.public_key().public_bytes_raw()
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_KEY_MISMATCH",
                "validator signing key differs from deployment authority",
            )
        expiry = min(now + _MAX_AUTHORITY_AGE, authority.valid_until)
        unsigned = SignedFiscalDiagnosticFocusWitnessV1(
            witness=witness,
            authority_id=authority.authority_id,
            principal_id=authority.principal_id,
            role=authority.role,
            key_id=authority.key_id,
            signed_at=now,
            expires_at=expiry,
            signature="0" * 128,
        )
        return unsigned.model_copy(
            update={"signature": key.sign(unsigned.signing_bytes()).hex()}
        )

    def _existing(
        self,
        artifact_id: str,
        authority: FiscalFocusValidatorAuthorityV1,
        reader: FiscalArtifactRead,
    ) -> SignedFiscalDiagnosticFocusWitnessV1 | None:
        if reader.current(artifact_id) is None:
            return None
        return self._read_envelope(artifact_id, authority, reader)

    def _read_envelope(
        self,
        artifact_id: str,
        authority: FiscalFocusValidatorAuthorityV1,
        reader: FiscalArtifactRead,
    ) -> SignedFiscalDiagnosticFocusWitnessV1:
        record = reader.get(artifact_id)
        raw = reader.read(artifact_id)
        envelope = SignedFiscalDiagnosticFocusWitnessV1.model_validate_json(raw)
        expected_dependencies = _witness_dependency_hashes(
            envelope.witness, authority.key_id
        )
        if (
            record.artifact_id != artifact_id
            or record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or record.dependency_hashes != expected_dependencies
            or hashlib.sha256(raw).hexdigest() != record.content_hash
            or raw != canonical_bytes(envelope.model_dump(mode="json"))
            or envelope.artifact_id != artifact_id
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_INVALID",
                "focus witness metadata differs from its signed value",
            )
        self._check_envelope_current(envelope, authority)
        try:
            authority.public_key().verify(
                bytes.fromhex(envelope.signature), envelope.signing_bytes()
            )
        except (InvalidSignature, ValueError) as error:
            raise SnapshotError(
                "FISCAL_FOCUS_SIGNATURE_INVALID", "focus witness signature is invalid"
            ) from error
        return envelope

    def _check_envelope_current(
        self,
        envelope: SignedFiscalDiagnosticFocusWitnessV1,
        authority: FiscalFocusValidatorAuthorityV1,
    ) -> None:
        now = self._now()
        if (
            envelope.authority_id != authority.authority_id
            or envelope.principal_id != authority.principal_id
            or envelope.role != authority.role
            or envelope.key_id != authority.key_id
            or authority.status != "active"
            or authority.valid_until <= now
            or envelope.expires_at <= now
            or envelope.signed_at > now
            or envelope.expires_at > authority.valid_until
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_INVALID",
                "focus witness is expired, revoked, or bound to a different authority",
            )

    def _verify_current_binding(
        self,
        envelope: SignedFiscalDiagnosticFocusWitnessV1,
        evidence: FiscalOriginalValidationEvidenceV1,
        source_ref: ArtifactRefV1,
        binding: FiscalDiagnosticFocusSourceBindingV1,
    ) -> None:
        self._require_refused_focus_source(evidence, source_ref)
        witness = envelope.witness
        current = FiscalDiagnosticFocusSourceBindingV1.model_validate(
            witness.model_dump(mode="python", exclude={"protocol", "actual_focus"})
        )
        if witness.source_validation_ref != source_ref or current != binding:
            raise SnapshotError(
                "FISCAL_FOCUS_WITNESS_SOURCE_MISMATCH",
                "focus witness no longer matches the retained source closure",
            )

    def _current_authority(self) -> FiscalFocusValidatorAuthorityV1:
        authority = self._authority()
        if authority.role != _FOCUS_ROLE or authority.status != "active":
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_INVALID",
                "focus validator authority is not active",
            )
        if authority.valid_until <= self._now():
            raise SnapshotError(
                "FISCAL_FOCUS_AUTHORITY_INVALID",
                "focus validator authority has expired",
            )
        return authority

    def _worker_digest(self) -> str:
        path = Path(__file__)
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SnapshotError(
                "FISCAL_FOCUS_CLOCK_INVALID", "focus clock must be timezone-aware"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _deadline_error() -> SecSourceError:
        return SecSourceError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal focus witness deadline expired",
            retryable=True,
        )

    def _check_deadline(self, deadline_at: datetime) -> float:
        now = self._now()
        if deadline_at.utcoffset() is None or deadline_at <= now:
            raise self._deadline_error()
        return (deadline_at - now).total_seconds()


@dataclass(frozen=True)
class FiscalFocusWitnessRead:
    owner: FiscalDiagnosticFocusWitnessOwner
    reader: FiscalArtifactRead
    source: FiscalSourceRead
    content: FiscalSourceContentRead
    runtime: FiscalParserRuntimeRead
    _witness: SignedFiscalDiagnosticFocusWitnessV1
    authority: FiscalFocusValidatorAuthorityV1
    deadline_at: datetime
    artifacts: EvidenceArtifactStore
    closure: FiscalSourceClosure
    content_store: ContentAddressedStore

    @property
    def witness(self) -> SignedFiscalDiagnosticFocusWitnessV1:
        return self._witness.model_copy(deep=True)

    @property
    def records(self) -> tuple[tuple[str, ArtifactRecordV1 | None], ...]:
        return self.reader.records

    def check_current(self) -> None:
        with metadata_operation_budget(
            partial(self.owner._check_deadline, self.deadline_at),
            self.owner._deadline_error,
        ):
            self._check_current()

    def _check_current(self) -> None:
        if (
            self.owner._artifacts is not self.artifacts
            or self.owner._closure is not self.closure
            or self.owner._content is not self.content_store
        ):
            raise SnapshotError(
                "FISCAL_FOCUS_RUNTIME_CHANGED", "focus source owner changed"
            )
        self.source.check_current()
        outcome = self.source.evidence.outcome
        if not isinstance(outcome, FiscalValidationCompleteRefusedV1):
            raise SnapshotError(
                "FISCAL_FOCUS_SOURCE_NOT_REFUSED", "source is not complete"
            )
        profile = self.owner._runtime_profile(outcome)
        self.runtime.check_current(
            profile, self.owner._taxonomy_cache_dir, outcome.runtime.delivery_revision
        )
        self.content.check_current()
        self.reader.check_bodies()
        witness = self._witness.witness
        if (
            self.owner._worker_digest() != witness.worker_module_sha256
            or dqc_applicability_policy_digest(witness.filing_context.dqc_version)
            != witness.applicability_policy_digest
        ):
            raise SnapshotError("FISCAL_FOCUS_RUNTIME_CHANGED", "focus policy changed")
        self.owner._check_current(
            self.reader, self.authority, outcome.runtime, self.deadline_at
        )
        self.owner._check_envelope_current(self._witness, self.authority)


def _read_focus_configuration(path: Path, *, private_key: bool) -> bytes:
    maximum_bytes = 16_384
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > maximum_bytes
                or (private_key and metadata.st_mode & 0o077)
            ):
                raise SnapshotError(
                    "FISCAL_FOCUS_AUTHORITY_INVALID",
                    "focus configuration requires bounded regular files and a private signing key",
                )
            content = source.read(maximum_bytes + 1)
            if len(content) > maximum_bytes:
                raise SnapshotError(
                    "FISCAL_FOCUS_AUTHORITY_INVALID",
                    "focus configuration exceeds its byte limit",
                )
            return content
    except OSError as error:
        raise SnapshotError(
            "FISCAL_FOCUS_AUTHORITY_INVALID",
            "focus configuration could not be read as a regular file",
        ) from error


def load_validator_authority(path: Path) -> FiscalFocusValidatorAuthorityV1:
    try:
        return FiscalFocusValidatorAuthorityV1.model_validate_json(
            _read_focus_configuration(path, private_key=False)
        )
    except ValidationError as error:
        raise SnapshotError(
            "FISCAL_FOCUS_AUTHORITY_INVALID", "focus validator authority is invalid"
        ) from error


def load_validator_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(
            _read_focus_configuration(path, private_key=True), password=None
        )
    except (ValueError, TypeError) as error:
        raise SnapshotError(
            "FISCAL_FOCUS_AUTHORITY_INVALID", "focus validator signing key is invalid"
        ) from error
    if not isinstance(key, Ed25519PrivateKey):
        raise SnapshotError(
            "FISCAL_FOCUS_AUTHORITY_INVALID",
            "focus validator requires an Ed25519 private key",
        )
    return key


def configured_focus_authority() -> FiscalFocusValidatorAuthorityV1:
    path = os.getenv("FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE")
    if not path:
        raise SnapshotError(
            "FISCAL_FOCUS_AUTHORITY_UNCONFIGURED",
            "fiscal focus validator authority is not configured",
        )
    return load_validator_authority(Path(path))


def configured_focus_private_key() -> Ed25519PrivateKey:
    path = os.getenv("FUNDAMENTAL_FISCAL_FOCUS_PRIVATE_KEY_FILE")
    if not path:
        raise SnapshotError(
            "FISCAL_FOCUS_AUTHORITY_UNCONFIGURED",
            "fiscal focus validator signing key is not configured",
        )
    return load_validator_private_key(Path(path))
