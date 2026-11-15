"""Assemble security release inputs from retained automatic preparation evidence."""

from __future__ import annotations

import hashlib
from typing import TypeVar

from pydantic import BaseModel

from .automatic_data_release import (
    AutomaticDataReleasePolicyV1,
    AutomaticDataReleaseRequestV1,
)
from .automatic_mapping_batch import (
    AutomaticMappingBatchDecisionV1,
    AutomaticMappingBatchRequestV1,
)
from .command_artifacts import EvidenceArtifactStore
from .conditional_capital_contracts import ConditionalCapitalPolicyV1
from .conditional_reinvestment_contracts import ConditionalReinvestmentPolicyV1
from .contracts import CanonicalFactV1, SourceSnapshotV1
from .data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseContentRequestV1,
    DataReleaseError,
    DataReleaseManifestV1,
    FactRefV1,
    MappingRefV1,
    SnapshotRefV1,
)
from .equity_dilution import AWARD_FACT_FIELDS
from .facts import CanonicalMappingV1, canonical_fact_digest, resolve_canonical_facts
from .serialization import sha256_digest
from .source_plan_contracts import AutomaticSourcePreparationPlanV1
from .taxonomy_evidence import TAXONOMY_CACHE_ARCHIVE_ROLE
from .working_capital import ValuationWorkingCapitalPolicyV1


ModelT = TypeVar("ModelT", bound=BaseModel)


def read_preparation_release_artifact(
    artifacts: EvidenceArtifactStore, ref: ArtifactRefV1, model: type[ModelT]
) -> ModelT:
    record = artifacts.get(ref.artifact_id)
    raw = artifacts.read(ref.artifact_id)
    if (
        record.status != "valid"
        or record.retention != "evidence"
        or record.content_hash != ref.content_hash
        or record.media_type != ref.media_type
        or hashlib.sha256(raw).hexdigest() != ref.content_hash
        or ref.media_type != "application/json"
    ):
        raise DataReleaseError(
            "AUTOMATIC_PREPARATION_ARTIFACT_MISMATCH",
            "release assembly requires exact retained JSON evidence",
        )
    return model.model_validate_json(raw)


def _canonical_refs(refs: tuple[ArtifactRefV1, ...]) -> tuple[ArtifactRefV1, ...]:
    identities: dict[str, tuple[str, str]] = {}
    unique = {}
    for ref in refs:
        identity = (ref.content_hash, ref.media_type)
        if identities.setdefault(ref.artifact_id, identity) != identity:
            raise DataReleaseError(
                "DATA_RELEASE_ARTIFACT_REFERENCE_CONFLICT",
                "release assembly received conflicting artifact identities",
            )
        unique[(ref.artifact_id, ref.role)] = ref
    return tuple(unique[key] for key in sorted(unique))


def select_preparation_release_facts(
    facts: tuple[CanonicalFactV1, ...], snapshot: SourceSnapshotV1
) -> tuple[tuple[CanonicalFactV1, ...], tuple[CanonicalFactV1, ...]]:
    """Use the canary's owning PIT selector for each comparative history period."""
    periods: dict[tuple[object, ...], list[CanonicalFactV1]] = {}
    selected: set[str] = set()
    decisions: list[CanonicalFactV1] = []
    for fact in facts:
        if fact.normalized_field in AWARD_FACT_FIELDS:
            selected.add(fact.fact_id)
        else:
            key = (
                fact.normalized_field,
                fact.period_start,
                fact.period_end,
                fact.instant,
            )
            periods.setdefault(key, []).append(fact)
    for candidates in periods.values():
        resolved = resolve_canonical_facts(
            candidates,
            snapshot=snapshot,
            valuation_timestamp=snapshot.valuation_timestamp,
            required_fields=(candidates[0].normalized_field,),
        )
        selected.update(fact.fact_id for fact in resolved)
        decisions.extend(resolved)
    # Keep stored fact digests. Selector annotations belong to separate evidence.
    return (
        tuple(
            sorted(
                (fact for fact in facts if fact.fact_id in selected),
                key=lambda fact: fact.fact_id,
            )
        ),
        tuple(sorted(decisions, key=lambda fact: fact.fact_id)),
    )


def assemble_preparation_release(
    *,
    plan: AutomaticSourcePreparationPlanV1,
    snapshot: SourceSnapshotV1,
    facts: tuple[CanonicalFactV1, ...],
    mappings: tuple[CanonicalMappingV1, ...],
    batch_refs: tuple[ArtifactRefV1, ...],
    artifacts: EvidenceArtifactStore,
    policy: AutomaticDataReleasePolicyV1,
    working_capital_policy: ValuationWorkingCapitalPolicyV1 | None,
    conditional_capital_policy: ConditionalCapitalPolicyV1 | None,
    prepared_refs: tuple[ArtifactRefV1, ...],
    conditional_reinvestment_policy: ConditionalReinvestmentPolicyV1 | None = None,
) -> AutomaticDataReleaseRequestV1:
    """Compile identities only; owning content validators decide release eligibility."""
    if len(batch_refs) != len(plan.ingestions):
        raise DataReleaseError(
            "AUTOMATIC_PREPARATION_MAPPING_EVIDENCE_MISSING",
            "every planned original requires its retained automatic mapping batch",
        )
    evidence: list[ArtifactRefV1] = []
    approvals: dict[str, AutomaticMappingApprovalV1] = {}
    for ingestion, ref in zip(plan.ingestions, batch_refs, strict=True):
        if ref.role != "automatic-mapping-batch-decision-v1":
            raise DataReleaseError(
                "AUTOMATIC_PREPARATION_MAPPING_EVIDENCE_MISMATCH",
                "release assembly requires the automatic batch decision role",
            )
        batch = read_preparation_release_artifact(
            artifacts, ref, AutomaticMappingBatchDecisionV1
        )
        input_id = "automatic-mapping-batch-input-" + batch.input_digest
        record = artifacts.get(input_id)
        input_ref = ArtifactRefV1(
            artifact_id=input_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role="automatic-mapping-batch-input-v1",
        )
        request = read_preparation_release_artifact(
            artifacts, input_ref, AutomaticMappingBatchRequestV1
        )
        if (
            sha256_digest(request) != batch.input_digest
            or request.source_revision != plan.source_revision
            or batch.source_revision != plan.source_revision
            or request.evaluator_id != ingestion.evaluator_id
            or request.mapping_version != ingestion.mapping_version
            or request.model_version != ingestion.model_version
            or request.requirements.digest != ingestion.requirements_digest
            or batch.requirements != request.requirements
            or batch.model_version != request.model_version
            or batch.policy_digest != ingestion.mapping_policy_digest
            or request.original.source.cik != ingestion.cik
            or request.original.source.accession_number
            != ingestion.filing.accession_number
            or request.original.decision_at != ingestion.valuation_timestamp
            or request.security_identity != ingestion.identity
        ):
            raise DataReleaseError(
                "AUTOMATIC_PREPARATION_MAPPING_EVIDENCE_MISMATCH",
                "retained batch must match the exact original preparation plan",
            )
        evidence.extend((ref, input_ref, *request.evidence_refs))
        for role in batch.roles:
            for decision in role.proposal_decisions():
                if decision.status != "approved":
                    continue
                assert decision.approval is not None and decision.decision is not None
                approval = read_preparation_release_artifact(
                    artifacts, decision.approval, AutomaticMappingApprovalV1
                )
                previous = approvals.setdefault(approval.mapping_id, approval)
                if previous != approval:
                    raise DataReleaseError(
                        "AUTOMATIC_PREPARATION_MAPPING_EVIDENCE_MISMATCH",
                        "one mapping cannot have conflicting approval evidence",
                    )
                evidence.extend((decision.decision, decision.approval))
    if not mappings or {item.decision_id for item in mappings} != approvals.keys():
        raise DataReleaseError(
            "AUTOMATIC_PREPARATION_MAPPING_EVIDENCE_MISMATCH",
            "release mappings must exactly match source-replayed automatic approvals",
        )
    selected_facts, selection_decisions = select_preparation_release_facts(
        facts, snapshot
    )
    selection = {
        "protocol": "automatic-preparation-fact-selection-v1",
        "snapshot_manifest_digest": snapshot.manifest_digest,
        "input_facts": tuple(
            FactRefV1(fact_id=fact.fact_id, fact_digest=canonical_fact_digest(fact))
            for fact in sorted(facts, key=lambda fact: fact.fact_id)
        ),
        "selected_fact_ids": tuple(fact.fact_id for fact in selected_facts),
        "decisions": selection_decisions,
    }
    selected_pub = artifacts.put_with_receipt(
        "automatic-preparation-fact-selection-" + sha256_digest(selection),
        selection,
        (
            snapshot.manifest_digest,
            *(
                canonical_fact_digest(fact)
                for fact in sorted(facts, key=lambda fact: fact.fact_id)
            ),
        ),
    )
    evidence.append(
        ArtifactRefV1(
            artifact_id=selected_pub.artifact.artifact_id,
            content_hash=selected_pub.artifact.content_hash,
            media_type=selected_pub.artifact.media_type,
            role="automatic-preparation-fact-selection-v1",
        )
    )
    used_mappings = {fact.mapping_decision_id for fact in selected_facts}
    mapping_refs = tuple(
        MappingRefV1(mapping_id=item.decision_id, mapping_digest=sha256_digest(item))
        for item in sorted(mappings, key=lambda item: item.decision_id)
        if item.decision_id in used_mappings
    )
    if {item.mapping_id for item in mapping_refs} != used_mappings:
        raise DataReleaseError(
            "AUTOMATIC_PREPARATION_MAPPING_EVIDENCE_MISMATCH",
            "selected facts must use source-replayed automatic mappings",
        )
    fact_refs = tuple(
        FactRefV1(fact_id=item.fact_id, fact_digest=canonical_fact_digest(item))
        for item in selected_facts
    )
    refs = _canonical_refs((*evidence, *prepared_refs))
    taxonomy = tuple(
        ref
        for ref in refs
        if ref.role in {TAXONOMY_CACHE_ARCHIVE_ROLE, "sec-taxonomy-manifest-v1"}
    )
    payload = dict(
        profile_id=plan.release_profile_id,
        release_id="automatic-preparation-"
        + sha256_digest(
            {
                "plan": plan.digest,
                "snapshot": snapshot.manifest_digest,
                "refs": refs,
                "facts": fact_refs,
                "mappings": mapping_refs,
                "policy": policy,
            }
        ),
        created_at=snapshot.captured_at,
        snapshot_refs=(
            SnapshotRefV1(
                snapshot_id=snapshot.snapshot_id,
                manifest_digest=snapshot.manifest_digest,
                facts=fact_refs,
                fact_set_digest=sha256_digest(fact_refs),
            ),
        ),
        mapping_refs=mapping_refs,
        taxonomy_refs=taxonomy,
        parser_version=snapshot.parser_version,
        quality_profile_digest=policy.quality_profile_digest,
        required_fields=plan.requirements_profile.required_fact_fields,
        artifact_refs=tuple(ref for ref in refs if ref not in taxonomy),
    )
    if working_capital_policy is not None:
        payload["valuation_working_capital_policy"] = working_capital_policy
    if conditional_capital_policy is not None:
        payload["conditional_capital_policies"] = (conditional_capital_policy,)
    if (plan.conditional_reinvestment_recipe is None) != (
        conditional_reinvestment_policy is None
    ) or (
        conditional_reinvestment_policy is not None
        and conditional_reinvestment_policy.recipe
        != plan.conditional_reinvestment_recipe
    ):
        raise DataReleaseError(
            "AUTOMATIC_PREPARATION_REINVESTMENT_UNBOUND",
            "release assembly requires the plan's exact bound forward policy",
        )
    if conditional_reinvestment_policy is not None:
        payload["conditional_reinvestment_policies"] = (
            conditional_reinvestment_policy,
        )
    manifest = DataReleaseManifestV1.model_validate(
        payload | {"manifest_digest": sha256_digest(payload)}
    )
    return AutomaticDataReleaseRequestV1(
        manifest=manifest,
        content=DataReleaseContentRequestV1(
            source_revision=plan.source_revision,
            evidence_refs=refs,
            mapping_reviews=tuple(approvals[ref.mapping_id] for ref in mapping_refs),
        ),
    )
