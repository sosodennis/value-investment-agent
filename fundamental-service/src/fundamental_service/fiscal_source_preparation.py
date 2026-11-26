from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
from pathlib import Path

from .artifact_evidence import read_retained_artifact
from .data_releases import ArtifactRefV1
from .fiscal_classification_contracts import (
    FiscalClassifierReviewExecutionV1,
    FiscalSourceAccountingReviewV1,
    FiscalSourcePreparationExecutionV1,
    FiscalRecordClassificationCommandV2,
)
from .fiscal_classification_source import FiscalClassificationSource
from .fiscal_source_accounting_policy import source_accounting_policy_identity
from .fiscal_source_accounting_policy_contracts import read_accounting_record
from .fiscal_source_closure import FiscalArtifactRead
from .fiscal_source_producer_contracts import (
    FiscalAccountingAccreditationV1,
    FiscalClassifierReviewExecutionV2,
    FiscalProducerInvocationV1,
    FiscalProducerOrderV1,
    SignedFiscalSourcePreparationExecutionV2,
)
from .serialization import canonical_bytes, sha256_digest
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
)
from .snapshots import SnapshotError

AccountingAccreditationProvider = Callable[[], ArtifactRefV1]


def fiscal_source_producer_executable_digest() -> str:
    root = Path(__file__).parent
    return sha256_digest(
        tuple(
            (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
            for name in (
                "fiscal_source_preparation.py",
                "fiscal_source_producer_runtime.py",
                "fiscal_source_producer_runner.py",
                "fiscal_source_producer_contracts.py",
                "fiscal_classification_contracts.py",
                "fiscal_source_classification.py",
                "fiscal_classification_review.py",
                "fiscal_classification_source.py",
                "fiscal_source_closure.py",
                "fiscal_source_validation.py",
                "fiscal_validation_contracts.py",
                "fiscal_focus_witness.py",
                "fiscal_source_accounting_policy.py",
                "fiscal_source_accounting_policy_contracts.py",
                "fiscal_admission_authority.py",
                "fiscal_admission_history.py",
                "history_recovery_contracts.py",
                "metadata.py",
                "snapshots.py",
                "content_publication.py",
                "serialization.py",
            )
        )
    )


def producer_invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_SOURCE_PRODUCER_INVALID", message)


def source_content_references(
    evidence: FiscalOriginalValidationEvidenceV1,
) -> tuple[ArtifactRefV1, ...]:
    outcome = evidence.outcome
    if not isinstance(outcome, FiscalValidationCompleteRefusedV1):
        raise producer_invalid("source content requires complete raw-refused evidence")
    integrity = outcome.integrity
    primary = tuple(
        receipt
        for receipt in outcome.responses
        if receipt.uri == integrity.primary_document_uri
    )
    if len(primary) != 1 or integrity.inline_documents:
        raise producer_invalid(
            "source producer content profile requires one primary SEC document"
        )
    media = primary[0].media_type
    selected = {
        (receipt.content_hash, receipt.media_type) for receipt in outcome.responses
    }
    selected.update(
        (digest, media)
        for digest in (
            integrity.normalized_content_hash,
            integrity.archive_member_hash,
            integrity.parser_input_hash,
        )
    )
    return tuple(
        ArtifactRefV1(
            role="fiscal-source-content-v1",
            artifact_id="fiscal-source-content-v1:"
            + sha256_digest((digest, media_type)),
            content_hash=digest,
            media_type=media_type,
        )
        for digest, media_type in sorted(selected)
    )


def _body(reader: FiscalArtifactRead, ref: ArtifactRefV1, role: str) -> bytes:
    if ref.role != role or ref.media_type != "application/json":
        raise producer_invalid("producer evidence role or media differs")
    return read_retained_artifact(reader, ref)


def read_producer_invocation(
    reader: FiscalArtifactRead,
    ref: ArtifactRefV1,
    *,
    role: str,
) -> tuple[FiscalProducerInvocationV1, FiscalProducerOrderV1]:
    raw = _body(reader, ref, "fiscal-source-producer-invocation-v1")
    invocation = FiscalProducerInvocationV1.model_validate_json(raw)
    order_raw = _body(reader, invocation.order_ref, "fiscal-source-producer-order-v1")
    order = FiscalProducerOrderV1.model_validate_json(order_raw)
    if (
        canonical_bytes(invocation) != raw
        or canonical_bytes(order) != order_raw
        or order.role != role
        or invocation.executable_digest != order.executable_digest
        or invocation.deployment_digest != order.deployment_digest
        or invocation.issuance != order.issuance
        or not order.valid_from <= invocation.started_at < order.expires_at
    ):
        raise producer_invalid("producer invocation differs from exact role order")
    return invocation, order


def read_source_preparation(
    reader: FiscalArtifactRead, ref: ArtifactRefV1
) -> SignedFiscalSourcePreparationExecutionV2:
    raw = _body(reader, ref, "fiscal-source-preparation-execution-v2")
    signed = SignedFiscalSourcePreparationExecutionV2.model_validate_json(raw)
    if canonical_bytes(signed) != raw:
        raise producer_invalid("source preparation bytes are not canonical")
    preparation = signed.preparation
    execution = preparation.execution
    invocation, order = read_producer_invocation(
        reader, preparation.invocation_ref, role="source_preparer"
    )
    if (
        order.source_request != preparation.request
        or order.authority_id != execution.authority_id
        or invocation.issuance != execution.issuance
        or invocation.started_at != execution.started_at
        or not execution.completed_at < order.expires_at
        or execution.execution_id != invocation.attempt_id
        or execution.source_validation_ref not in preparation.consumed_refs
    ):
        raise producer_invalid("preparation does not bind its actual source invocation")
    for dependency in preparation.consumed_refs:
        read_retained_artifact(reader, dependency)
    source_raw = read_retained_artifact(reader, execution.source_validation_ref)
    if hashlib.sha256(source_raw).hexdigest() != execution.source_binding_digest:
        raise producer_invalid(
            "preparation source binding differs from retained source"
        )
    evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(source_raw)
    if (
        canonical_bytes(evidence.model_dump(mode="json")) != source_raw
        or source_content_references(evidence) != preparation.source_content_refs
    ):
        raise producer_invalid(
            "preparation source content differs from exact source closure"
        )
    for content_ref in preparation.source_content_refs:
        read_retained_artifact(reader, content_ref)
    return signed


class FiscalSourceProducerEvidenceVerifier:
    def __init__(self, accreditation: AccountingAccreditationProvider) -> None:
        self.accreditation = accreditation

    def require_current(
        self,
        reference: ArtifactRefV1,
        expires_at: datetime,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        now: datetime,
    ) -> FiscalAccountingAccreditationV1:
        check_deadline()
        expected = self.accreditation()
        raw = _body(reader, reference, "fiscal-accounting-accreditation-v1")
        accreditation = FiscalAccountingAccreditationV1.model_validate_json(raw)
        if (
            expected != reference
            or raw != canonical_bytes(accreditation)
            or accreditation.policy != source_accounting_policy_identity()
            or accreditation.classifier_executable_digest
            != fiscal_source_producer_executable_digest()
            or not accreditation.valid_from
            <= now
            < expires_at
            <= accreditation.valid_until
        ):
            raise producer_invalid(
                "accounting policy accreditation is not current and exact"
            )
        read_retained_artifact(reader, accreditation.independent_review_ref)
        if self.accreditation() != expected:
            raise producer_invalid(
                "accounting accreditation changed during verification"
            )
        check_deadline()
        return accreditation

    def verify(
        self,
        command: FiscalRecordClassificationCommandV2,
        source: FiscalClassificationSource,
        review: FiscalSourceAccountingReviewV1,
        proof: FiscalClassifierReviewExecutionV2,
        preparation: SignedFiscalSourcePreparationExecutionV2,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        now: datetime,
    ) -> tuple[FiscalClassifierReviewExecutionV1, FiscalSourcePreparationExecutionV1]:
        check_deadline()
        expected = self.accreditation()
        accreditation = self.require_current(
            proof.accreditation_ref,
            command.expires_at,
            reader=reader,
            check_deadline=check_deadline,
            now=now,
        )
        invocation, order = read_producer_invocation(
            reader, proof.invocation_ref, role="classifier"
        )
        execution = proof.execution
        prep = preparation.preparation
        outcome = source.evidence.outcome
        if not isinstance(outcome, FiscalValidationCompleteRefusedV1):
            raise producer_invalid(
                "classification requires complete raw-refused content"
            )
        archive_refs = tuple(
            ref
            for ref in prep.source_content_refs
            if ref.content_hash == outcome.integrity.archive_hash
        )
        if (
            len(archive_refs) != 1
            or read_retained_artifact(reader, archive_refs[0]) != source.archive
        ):
            raise producer_invalid(
                "preparation archive content differs from current source"
            )
        prep_invocation, _ = read_producer_invocation(
            reader, prep.invocation_ref, role="source_preparer"
        )
        if (
            invocation.executable_digest != accreditation.classifier_executable_digest
            or invocation.issuance != execution.issuance
            or invocation.started_at != execution.started_at
            or invocation.attempt_id != execution.execution_id
            or order.authority_id != command.authority_id
            or order.order_id != command.command_id
            or order.preparation_ref != command.preparer_execution_ref
            or order.witness_ref != command.witness_ref
            or order.security_id != command.security_id
            or order.expires_at != command.expires_at
            or proof.preparation_ref != command.preparer_execution_ref
            or prep.execution.source_validation_ref != command.source_validation_ref
            or prep.request != source.evidence.request.selection
            or prep_invocation.executable_digest
            != accreditation.classifier_executable_digest
            or not accreditation.valid_from
            <= execution.started_at
            <= execution.completed_at
            < command.expires_at
        ):
            raise producer_invalid(
                "classifier execution differs from its trusted policy job"
            )
        basis_raw = _body(
            reader, proof.accounting_basis_ref, "fiscal-accounting-replay-v3"
        )
        record = read_accounting_record(basis_raw, check_deadline=check_deadline)
        if (
            record.review() != review
            or record.result.policy != accreditation.policy
            or record.result.source_evidence_sha256
            != sha256_digest(source.evidence.model_dump(mode="json"))
            or record.result.witness_sha256 != sha256_digest(source.witness)
            or record.result.scope_sha256 != source.scope.scope_digest
        ):
            raise producer_invalid(
                "accounting decision basis differs from current source review"
            )
        if self.accreditation() != expected:
            raise producer_invalid(
                "accounting accreditation changed during verification"
            )
        check_deadline()
        return execution, prep.execution
