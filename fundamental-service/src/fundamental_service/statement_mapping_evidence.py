from __future__ import annotations
from typing import Literal

from .artifact_evidence import EvidenceArtifactReader, read_retained_artifact
from .automatic_mapping import (
    AutomaticMappingRequestV1,
    automatic_mapping_policy_digest,
    automatic_mapping_proposals,
    evaluate_automatic_mapping,
)
from .automatic_mapping_batch import (
    StatementMappingBatchDecisionV1,
    StatementMappingBatchRequestV1,
)
from .automatic_mapping_evidence import AutomaticMappingEvidenceChecks
from .data_releases import ArtifactRefV1, DataReleaseError
from .mapping_input_storage import read_mapping_batch_input
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import canonical_bytes
from .statement_contracts import (
    StatementProfileV1,
    StatementScopeV1,
    StatementAnnualColumnV1,
    DurationStatementPeriodV1,
    InstantStatementPeriodV1,
    StatementMissingEvidenceV1,
    StatementPeriodV1,
    StatementRowDefinitionV1,
    statement_period_id,
)
from .contracts import MissingValueV1, QualityStatus


def verify_statement_mapping_outcomes(
    reference: ArtifactRefV1,
    *,
    original: OriginalIssuerEvidenceV1,
    artifacts: EvidenceArtifactReader,
    source_revision: str,
    profile: StatementProfileV1,
    mapping_version: str,
) -> StatementMappingBatchDecisionV1:
    batch = StatementMappingBatchDecisionV1.model_validate_json(
        read_retained_artifact(artifacts, reference)
    )
    checks = AutomaticMappingEvidenceChecks()
    _, request = read_mapping_batch_input(
        batch.input_digest,
        StatementMappingBatchRequestV1,
        artifacts=artifacts,
        original_checks=checks.originals,
        input_digests=checks.identities,
    )
    if (
        request.original != original
        or request.statement_profile != profile
        or batch.statement_profile != profile
        or request.source_revision != source_revision
        or batch.source_revision != source_revision
        or batch.policy_digest != automatic_mapping_policy_digest()
        or request.mapping_version != mapping_version
    ):
        raise DataReleaseError(
            "STATEMENT_MAPPING_OUTCOME_CONTEXT_MISMATCH",
            "statement mapping outcomes differ from their original source and installed policy",
        )
    contents = {
        ref.content_hash: read_retained_artifact(artifacts, ref)
        for ref in request.evidence_refs
    }
    for role in batch.roles:
        proposals = automatic_mapping_proposals(
            role.normalized_field,
            mapping_version=mapping_version,
            original=original,
            observed_only=True,
            input_digests=checks.identities,
        )
        outcomes = role.proposal_decisions()
        if not proposals:
            if (
                len(outcomes) != 1
                or role.status != "abstain"
                or role.reason_codes != ("MAPPING_AUTOMATIC_RULE_UNSUPPORTED",)
                or role.decision is not None
                or role.approval is not None
            ):
                raise DataReleaseError(
                    "STATEMENT_MAPPING_OUTCOME_MISMATCH",
                    "unsupported statement role differs from its evaluator outcome",
                )
            continue
        if len(outcomes) != len(proposals):
            raise DataReleaseError(
                "STATEMENT_MAPPING_OUTCOME_MISMATCH",
                "statement mapping alternatives differ from the installed policy",
            )
        for proposal, outcome in zip(proposals, outcomes, strict=True):
            single = AutomaticMappingRequestV1.model_validate(
                {
                    "source_revision": request.source_revision,
                    "evaluator_id": request.evaluator_id,
                    "original": request.original,
                    "integrity": request.integrity,
                    "evidence_refs": request.evidence_refs,
                    "security_identity": request.security_identity,
                    "proposal": proposal,
                },
                context=checks.originals,
            )
            expected = evaluate_automatic_mapping(
                single, contents=contents, evidence_checks=checks
            )
            if outcome.decision is None:
                raise DataReleaseError(
                    "STATEMENT_MAPPING_OUTCOME_MISMATCH",
                    "statement mapping evaluation lacks its retained decision",
                )
            raw = read_retained_artifact(artifacts, outcome.decision)
            if (
                raw != canonical_bytes(expected)
                or outcome.status != expected.status
                or outcome.reason_codes != expected.reason_codes
            ):
                raise DataReleaseError(
                    "STATEMENT_MAPPING_OUTCOME_MISMATCH",
                    "statement row mapping outcome does not reproduce",
                )
    return batch


def statement_missing_evidence(
    batch: StatementMappingBatchDecisionV1,
    reference: ArtifactRefV1,
    scope: StatementScopeV1,
    column: StatementAnnualColumnV1,
    observed_fields: set[str],
) -> tuple[StatementMissingEvidenceV1, ...]:
    missing = []
    definitions: dict[str, StatementRowDefinitionV1] = {
        row.row_id: row for row in batch.statement_profile.rows
    }
    for role in batch.roles:
        if role.normalized_field in observed_fields:
            continue
        codes = tuple(
            sorted(
                {
                    code
                    for outcome in role.proposal_decisions()
                    for code in outcome.reason_codes
                }
            )
        ) or ("STATEMENT_ROW_EVIDENCE_UNRESOLVED",)
        status: Literal["unresolved", "missing", "unsupported"] = "unresolved"
        reason = "No approved observation is available for this row in the original."
        if "MAPPING_STATEMENT_ROW_NOT_PRESENTED" in codes:
            status = "missing"
            reason = "Not separately presented in the reviewed primary statement."
        elif "MAPPING_AUTOMATIC_RULE_UNSUPPORTED" in codes or any(
            code.endswith("SCOPE_UNREVIEWED") for code in codes
        ):
            status = "unsupported"
            reason = "The installed mapping policy cannot establish this primary statement row."
        period: StatementPeriodV1 = column.period
        if definitions[
            role.normalized_field
        ].statement == "balance_sheet" and isinstance(
            period, DurationStatementPeriodV1
        ):
            period = InstantStatementPeriodV1(instant=period.period_end)
        missing.append(
            StatementMissingEvidenceV1.model_validate(
                dict(
                    row_id=role.normalized_field,
                    period_id=statement_period_id(scope, period),
                    missing=MissingValueV1(status=status, reason=reason),
                    quality_status=QualityStatus.PROVISIONAL,
                    issue_codes=codes,
                    evidence_refs=(reference,),
                )
            )
        )
    return tuple(missing)
