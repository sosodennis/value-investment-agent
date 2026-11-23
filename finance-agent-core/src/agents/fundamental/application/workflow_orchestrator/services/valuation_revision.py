"""Reproduce a retained automatic preparation before one server-owned edit."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.valuation_revision_port import (
    FundamentalRevisionSourceReaderPort,
)
from src.agents.fundamental.application.workflow_orchestrator.services.snapshot_identity_binding import (
    SnapshotIdentitySelectionPolicy,
    identity_matches_resolver,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalValuationRevisionV1,
)
from src.shared.artifacts.fundamental_contracts import (
    FundamentalValuationPreparationResultV1,
)
from src.shared.internal_services import InternalPrincipal
from src.shared.kernel.types import JSONObject


def _failure(code: str, message: str) -> FundamentalServiceFailure:
    return FundamentalServiceFailure(code, message, retryable=False, status_code=422)


async def prepare_retained_valuation_revision(
    revision: FundamentalValuationRevisionV1,
    *,
    source_reader: FundamentalRevisionSourceReaderPort,
    current_thread_id: str,
    requested_model_id: str | None,
    requested_model_version: str | None,
    requested_policy_id: str | None,
    identity: JSONObject,
    identity_selection_policy: SnapshotIdentitySelectionPolicy,
    client: FundamentalServiceClient,
    principal: InternalPrincipal,
    correlation_id: str,
    deadline_at: datetime,
    modified_at: datetime,
) -> FundamentalValuationPreparationResultV1:
    source = await source_reader.read_source(
        revision.source,
        principal=principal,
        current_thread_id=current_thread_id,
    )
    original = source.automatic_preparation
    if original is None or original.status != "prepared" or original.input is None:
        raise _failure(
            "REVISION_SOURCE_INVALID", "Source report has no complete preparation"
        )
    if (
        any(
            evidence.method == "manual" or evidence.manual_provenance is not None
            for evidence in original.assumptions_evidence
        )
        or "MANUAL_OVERRIDE_APPLIED" in original.issue_codes
        or "MANUAL_OVERRIDE_APPLIED" in source.quality.issue_codes
        or any(
            isinstance(provenance := value.get("provenance"), Mapping)
            and provenance.get("conditional_revision_ref") is not None
            for value in (original.input, source.valuation_input)
        )
    ):
        raise _failure(
            "REVISION_SOURCE_READ_ONLY", "Manual or revised reports are read-only"
        )
    automatic_evidence = tuple(
        evidence
        for evidence in original.assumptions_evidence
        if evidence.path == revision.path
    )
    if len(automatic_evidence) != 1 or not automatic_evidence[0].editable:
        raise _failure(
            "REVISION_PATH_UNAVAILABLE",
            "Source preparation has no unique editable evidence for this path",
        )
    if original.preparation_digest != revision.source.preparation_digest:
        raise _failure(
            "REVISION_SOURCE_BINDING_MISMATCH",
            "Source preparation does not match the requested digest",
        )
    original_input = original.input
    canonical_identity = source.facts.identity.model_dump(mode="json")
    context = original_input.get("valuation_context")
    if not isinstance(context, Mapping):
        raise _failure("REVISION_SOURCE_INVALID", "Source valuation context is missing")
    release_digest = context.get("data_release_manifest_digest")
    if (
        original_input.get("identity") != canonical_identity
        or not identity_matches_resolver(
            identity, canonical_identity, policy=identity_selection_policy
        )
        or source.snapshot_id != context.get("data_snapshot_id")
        or source.hashes.data_release_manifest_digest != release_digest
        or original_input.get("model_id") != original.model_id
        or original_input.get("model_version") != original.model_version
        or original_input.get("policy_id") != original.policy_id
        or requested_model_id not in (None, original.model_id)
        or requested_model_version not in (None, original.model_version)
        or requested_policy_id not in (None, original.policy_id)
    ):
        raise _failure(
            "REVISION_SOURCE_BINDING_MISMATCH",
            "Source identity, snapshot, release, model, or policy does not match",
        )
    if not isinstance(release_digest, str) or len(release_digest) != 64:
        raise _failure("REVISION_SOURCE_INVALID", "Source release is missing")
    automatic = await client.prepare_valuation(
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": source.snapshot_id,
            "data_release_manifest_digest": release_digest,
            "model_id": original.model_id,
        },
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    if (
        automatic.preparation_digest != original.preparation_digest
        or automatic.model_dump(mode="json", exclude_unset=True)
        != original.model_dump(mode="json", exclude_unset=True)
    ):
        raise _failure(
            "REVISION_SOURCE_STALE",
            "Source automatic preparation no longer reproduces exactly",
        )
    provenance: JSONObject = {
        "author": principal.subject_id,
        "modified_at": modified_at.astimezone(UTC).isoformat(),
        "reason": revision.reason,
        "automatic_preparation_digest": original.preparation_digest,
    }
    if revision.forward_reference is not None:
        provenance["forward_reference"] = revision.forward_reference.model_dump(
            mode="json"
        )
    response = await client.execute(
        "override_prepared_valuation",
        {
            "contract_version": "fundamental.v1",
            "preparation": original.model_dump(mode="json", exclude_unset=True),
            "path": revision.path,
            "value": revision.value,
            "provenance": provenance,
        },
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    try:
        revised = FundamentalValuationPreparationResultV1.model_validate(
            response.result
        )
        revised_assumptions = (revised.input or {}).get("assumptions")
        if not isinstance(revised_assumptions, Mapping):
            raise ValueError("revised assumptions are missing")
        terminal_growth = revised_assumptions.get("terminal_growth")
        if not isinstance(terminal_growth, str) or Decimal(terminal_growth) != Decimal(
            revision.value
        ):
            raise ValueError("revised terminal growth does not match the request")
    except (TypeError, ValueError, InvalidOperation) as error:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental service returned an invalid revision preparation",
            retryable=False,
            status_code=502,
        ) from error
    revised_context = (revised.input or {}).get("valuation_context")
    if (
        revised.status != "prepared"
        or revised.input is None
        or revised.input.get("identity") != canonical_identity
        or revised_context != context
        or revised.model_id != original.model_id
        or revised.model_version != original.model_version
        or revised.policy_id != original.policy_id
        or revised.policy_version != original.policy_version
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental revision changed immutable source bindings",
            retryable=False,
            status_code=502,
        )
    return revised
