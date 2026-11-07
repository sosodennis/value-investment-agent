"""Caller-owned orchestration for the Fundamental service cutover."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from src.agents.fundamental.application.fundamental_service_port import (
    FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.services.service_request_producer import (
    PreparedServiceValuation,
    prepare_service_valuation_request,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalFactsReadResultV1,
    FundamentalServiceResponseV1,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalRequestTimingV1,
    apply_request_timing,
)
from src.artifacts.public import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ArtifactReference,
    to_artifact_reference_payload,
)
from src.shared.internal_services import InternalPrincipal, get_request_principal
from src.shared.kernel.correlation import resolve_correlation_id
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

FundamentalNodeResult = WorkflowNodeResult
FundamentalAnalysisContext = dict[str, object]

_SERVICE_INPUT_KEY = "valuation_request"
_REQUIRED_INPUT_FIELDS = frozenset(
    {
        "contract_version",
        "identity",
        "valuation_context",
        "historical_facts",
        "assumptions",
        "uncertainty",
        "quality",
        "provenance",
        "model_id",
        "model_version",
    }
)
_SUPPORTED_INPUT_FIELDS = _REQUIRED_INPUT_FIELDS | {
    "policy_id",
    "input_digest",
    "caller_approval",
    "snapshot_selector",
    "requested_as_of",
    "fiscal_period_selector",
    "required_fields",
}
_LEGACY_INPUT_FIELDS = frozenset(
    {
        "financial_reports",
        "reports",
        "raw_financial_reports",
        "params_dump",
        "calculation_metrics",
        "intrinsic_value",
        "market_snapshot",
    }
)
_PROJECTION_FIELDS = (
    "status",
    "calculation_version",
    "calculation_status",
    "quality_status",
    "input_digest",
    "result_hash",
    "intrinsic_value",
    "per_share_value",
    "nodes",
    "assumptions",
    "model_version",
    "policy_version",
    "policy_id",
    "trace",
    "issue_codes",
    "missing_evidence",
    "snapshot_id",
    "evaluated_at",
    "correlation_id",
    "requested_samples",
    "valid_samples",
    "invalid_samples",
    "invalid_reasons",
    "invalid_draw_policy",
    "seed",
    "sampler_version",
    "quantiles",
    "convergence_diagnostics",
    "dominant_drivers",
    "sensitivity",
    "scenario_results",
    "artifact_references",
    "value_drivers",
)
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_QUALITY_STATUSES = frozenset(
    {"verified", "provisional", "degraded", "unsupported", "abstain", "error"}
)
_SCHEMA_DEFAULTS: tuple[tuple[tuple[str | int | None, ...], object], ...] = (
    (("assumptions", "bank"), None),
    (("assumptions", "forecast", "base_revenue"), None),
    (("assumptions", "trace", "description"), None),
    (("assumptions", "trace", "expression"), None),
    (("assumptions", "trace", "inputs"), ()),
    (("assumptions", "trace", "source_refs"), ()),
    (("uncertainty", "parameters"), ()),
    (("uncertainty", "parameters", None, "mean"), None),
    (("uncertainty", "parameters", None, "mode"), None),
    (("uncertainty", "samples"), None),
    (("uncertainty", "seed"), None),
    (("uncertainty", "correlations"), ()),
    (("uncertainty", "invalid_draw_policy"), None),
    (("uncertainty", "scenarios"), ()),
    (("uncertainty", "sensitivity"), ()),
)


class ServiceValuationRuntime(Protocol):
    def build_valuation_error_update(self, error: str) -> JSONObject: ...

    async def save_financial_reports(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...


def _as_mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    return value


def read_service_valuation_input(state: Mapping[str, object]) -> JSONObject:
    """Read the one canonical caller-owned input seam without deriving values."""

    raw_input = state.get("valuation_request")
    if raw_input is not None:
        return _validate_service_input(raw_input)
    raw_context = state.get("fundamental_analysis", {})
    context = _as_mapping(raw_context, context="fundamental_analysis")
    raw_input = context.get(_SERVICE_INPUT_KEY)
    return _validate_service_input(
        raw_input,
        context=f"fundamental_analysis.{_SERVICE_INPUT_KEY}",
    )


def _validate_service_input(
    raw_input: object,
    *,
    context: str = "valuation_request",
) -> JSONObject:
    input_mapping = _as_mapping(raw_input, context=context)
    has_selector = "snapshot_selector" in input_mapping
    has_request_timing = (
        "requested_as_of" in input_mapping or "required_fields" in input_mapping
    )
    required_fields = _REQUIRED_INPUT_FIELDS - (
        {"historical_facts"} if has_selector or has_request_timing else set()
    )
    missing = sorted(required_fields.difference(input_mapping))
    if missing:
        raise ValueError(
            "Fundamental service valuation input is missing required fields: "
            + ", ".join(missing)
        )
    if input_mapping.get("contract_version") != "fundamental.v1":
        raise ValueError("Fundamental valuation input must use fundamental.v1")
    legacy = sorted(_LEGACY_INPUT_FIELDS.intersection(input_mapping))
    if legacy:
        raise ValueError(
            "Fundamental valuation input contains legacy or raw fields: "
            + ", ".join(legacy)
        )
    unknown = sorted(set(input_mapping).difference(_SUPPORTED_INPUT_FIELDS))
    if unknown:
        raise ValueError(
            "Fundamental valuation input contains fields outside the frozen "
            "ValuationInputV1 contract: " + ", ".join(unknown)
        )
    for field in (
        "identity",
        "valuation_context",
        "assumptions",
        "uncertainty",
        "quality",
        "provenance",
    ):
        _as_mapping(input_mapping[field], context=f"valuation_request.{field}")
    uncertainty = _as_mapping(
        input_mapping["uncertainty"], context="valuation_request.uncertainty"
    )
    if uncertainty.get("mode") == "scenarios":
        raise ValueError(
            "scenario payloads are not part of the frozen ValuationInputV1 contract"
        )
    if "historical_facts" in input_mapping:
        historical_facts = input_mapping["historical_facts"]
        if not isinstance(historical_facts, list | tuple) or (
            not historical_facts and not has_selector
        ):
            raise ValueError("valuation_request.historical_facts must be non-empty")
    if has_selector:
        selector = _as_mapping(
            input_mapping["snapshot_selector"],
            context="valuation_request.snapshot_selector",
        )
        for field in (
            "contract_version",
            "identity",
            "valuation_timestamp",
            "source_selection_policy",
            "coverage_profile",
            "required_fields",
        ):
            if field not in selector:
                raise ValueError(f"snapshot_selector.{field} is required")
    for field in ("model_id", "model_version"):
        value = input_mapping[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"valuation_request.{field} must be a non-empty string")
    return dict(input_mapping)


def _response_result(response: FundamentalServiceResponseV1) -> Mapping[str, object]:
    result = response.result
    if not isinstance(result, Mapping):  # pragma: no cover - pydantic guard
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental service result is not an object",
            retryable=False,
            status_code=502,
        )
    return result


def _validated_input(
    result: Mapping[str, object],
) -> tuple[JSONObject, str, str, Mapping[str, object]]:
    raw_input = result.get("input")
    if not isinstance(raw_input, Mapping):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental validation response did not include input",
            retryable=False,
            status_code=502,
        )
    input_digest = result.get("input_digest")
    if not isinstance(input_digest, str) or not _DIGEST_PATTERN.fullmatch(input_digest):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental validation response did not include input_digest",
            retryable=False,
            status_code=502,
        )
    quality_status = result.get("quality_status")
    if not isinstance(quality_status, str) or not quality_status:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental validation response did not include quality_status",
            retryable=False,
            status_code=502,
        )
    policy_resolution = result.get("policy_resolution")
    if not isinstance(policy_resolution, Mapping):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental validation response did not include policy resolution",
            retryable=False,
            status_code=502,
        )
    input_policy_id = raw_input.get("policy_id")
    input_provenance = raw_input.get("provenance")
    input_policy_version = (
        input_provenance.get("policy_version")
        if isinstance(input_provenance, Mapping)
        else None
    )
    policy_digest = policy_resolution.get("policy_digest")
    if (
        result.get("contract_version") != "fundamental.v1"
        or raw_input.get("input_digest") != input_digest
        or policy_resolution.get("contract_version") != "fundamental.v1"
        or policy_resolution.get("input_digest") != input_digest
        or not isinstance(input_policy_id, str)
        or policy_resolution.get("policy_id") != input_policy_id
        or not isinstance(input_policy_version, str)
        or policy_resolution.get("policy_version") != input_policy_version
        or not isinstance(policy_digest, str)
        or not _DIGEST_PATTERN.fullmatch(policy_digest)
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental validation policy resolution is not bound to its input",
            retryable=False,
            status_code=502,
        )
    return dict(raw_input), input_digest, quality_status, policy_resolution


def _resolved_snapshot_input(
    input_payload: Mapping[str, object], result: Mapping[str, object]
) -> tuple[JSONObject, str]:
    """Bind service-owned snapshot and fact references into the caller request."""

    snapshot_id = result.get("snapshot_id")
    facts = result.get("historical_facts")
    resolved_identity = result.get("identity")
    resolved_timestamp = result.get("valuation_timestamp")
    resolved_policy = result.get("source_selection_policy")
    resolved_profile = result.get("coverage_profile")
    input_selector = input_payload.get("snapshot_selector")
    input_context = input_payload.get("valuation_context")
    input_selector = input_selector if isinstance(input_selector, Mapping) else {}
    input_context = input_context if isinstance(input_context, Mapping) else {}
    resolved_selector = (
        result.get("fiscal_period_selector")
        or input_selector.get("fiscal_period_selector")
        or input_context.get("fiscal_period_selector")
    )
    if resolved_selector is None:
        resolved_selector = {
            "version": "fundamental.fiscal-period-selector.v1",
            "mode": "latest_complete",
            "count": 3,
        }
    resolved_periods = result.get("resolved_fiscal_periods", ())
    period_resolution = result.get("fiscal_period_resolution")
    provenance_raw = result.get("provenance")
    source_selection_policy_version = (
        provenance_raw.get("policy_version")
        if isinstance(provenance_raw, Mapping)
        else None
    )
    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id
        or not isinstance(facts, list | tuple)
        or not facts
        or any(not isinstance(item, str) or not item for item in facts)
        or not isinstance(resolved_identity, Mapping)
        or not isinstance(resolved_timestamp, str)
        or not isinstance(resolved_policy, str)
        or not isinstance(resolved_profile, str)
        or not isinstance(resolved_selector, Mapping)
        or not isinstance(resolved_periods, list | tuple)
        or not isinstance(provenance_raw, Mapping)
        or not isinstance(source_selection_policy_version, str)
        or not source_selection_policy_version
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental snapshot resolution response is incomplete",
            retryable=False,
            status_code=502,
        )
    valuation_context = _as_mapping(
        input_payload["valuation_context"],
        context="valuation_request.valuation_context",
    )
    if not _payload_equal(resolved_identity, input_payload.get("identity")):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental snapshot resolution changed the requested identity",
            retryable=False,
            status_code=502,
        )
    provenance = _as_mapping(
        input_payload["provenance"], context="valuation_request.provenance"
    )
    updated = dict(input_payload)
    updated.pop("snapshot_selector", None)
    updated["historical_facts"] = list(facts)
    updated["valuation_context"] = {
        **valuation_context,
        "data_snapshot_id": snapshot_id,
        "valuation_timestamp": resolved_timestamp,
        "source_selection_policy": resolved_policy,
        "coverage_profile": resolved_profile,
        "fiscal_period_selector": dict(resolved_selector),
        "resolved_fiscal_periods": list(resolved_periods),
    }
    updated["provenance"] = {
        **provenance,
        **{
            key: value
            for key, value in provenance_raw.items()
            if value is not None and key != "policy_version"
        },
        "snapshot_id": snapshot_id,
        "fact_ids": list(facts),
        "fiscal_period_selector": dict(resolved_selector),
        "resolved_fiscal_periods": list(resolved_periods),
    }
    if isinstance(period_resolution, Mapping):
        updated["provenance"]["fiscal_period_resolution"] = dict(period_resolution)
    quality = result.get("quality")
    if isinstance(quality, str) and quality:
        current_quality = _as_mapping(
            input_payload["quality"], context="valuation_request.quality"
        )
        updated["quality"] = {
            **current_quality,
            "status": quality,
            "issue_codes": list(result.get("issue_codes", ())),
        }
    return updated, source_selection_policy_version


def _payload_equal(left: object, right: object) -> bool:
    """Compare JSON-shaped caller fields without changing their values."""

    try:
        return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
            right, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return left == right


def _is_schema_default(path: tuple[str | int, ...], value: object) -> bool:
    for pattern, expected in _SCHEMA_DEFAULTS:
        if len(pattern) == len(path) and all(
            candidate is None and isinstance(actual, int) or candidate == actual
            for candidate, actual in zip(pattern, path, strict=True)
        ):
            if _payload_equal(expected, value):
                return True
    return False


def _caller_values_preserved(
    supplied: object,
    returned: object,
    *,
    path: tuple[str | int, ...] = (),
) -> bool:
    """Preserve caller values and permit only known inert schema defaults."""

    if isinstance(supplied, Mapping):
        if not isinstance(returned, Mapping):
            return False
        for key, value in supplied.items():
            if key not in returned or not _caller_values_preserved(
                value, returned[key], path=path + (str(key),)
            ):
                return False
        return all(
            key in supplied or _is_schema_default(path + (str(key),), value)
            for key, value in returned.items()
        )
    if isinstance(supplied, list | tuple):
        return (
            isinstance(returned, list | tuple)
            and len(supplied) == len(returned)
            and all(
                _caller_values_preserved(left, right, path=path + (index,))
                for index, (left, right) in enumerate(
                    zip(supplied, returned, strict=True)
                )
            )
        )
    return _payload_equal(supplied, returned)


def _approval_request(
    *,
    input_payload: Mapping[str, object],
    input_digest: str,
    quality_status: str,
    validation_result: Mapping[str, object],
) -> JSONObject:
    issues = validation_result.get("issue_codes")
    issue_codes = (
        [item for item in issues if isinstance(item, str)]
        if isinstance(issues, list | tuple)
        else []
    )
    missing = validation_result.get("missing_evidence")
    missing_evidence = (
        [item for item in missing if isinstance(item, str)]
        if isinstance(missing, list | tuple)
        else []
    )
    assumptions = input_payload.get("assumptions")
    uncertainty = input_payload.get("uncertainty")
    return {
        "type": "valuation_approval",
        "contract_version": "v1",
        "ticker": _ticker_from_input(input_payload),
        "model_type": str(input_payload["model_id"]),
        "title": "Review Fundamental service assumptions",
        "description": (
            "The Fundamental service validated the explicit valuation input. "
            "Approve to run the stateless calculation, or reject to stop."
        ),
        "parameters": {
            "assumptions": assumptions,
            "uncertainty": uncertainty,
            "model_id": input_payload["model_id"],
            "model_version": input_payload["model_version"],
            "input_digest": input_digest,
            "quality_status": quality_status,
        },
        "audit_messages": issue_codes + missing_evidence,
    }


def _ticker_from_input(input_payload: Mapping[str, object]) -> str:
    identity = input_payload.get("identity")
    if isinstance(identity, Mapping):
        security_id = identity.get("security_id")
        issuer_id = identity.get("issuer_id")
        if isinstance(security_id, str) and security_id:
            return security_id
        if isinstance(issuer_id, str) and issuer_id:
            return issuer_id
    return "UNKNOWN"


def _approval_is_accepted(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("type") == "valuation_approval"
        and value.get("contract_version") == "v1"
        and value.get("decision") in {"approve", "reject"}
        and set(value) == {"type", "contract_version", "decision"}
    )


def _uncertainty_projection(
    response: FundamentalServiceResponseV1,
    *,
    expected_input_digest: str,
    expected_seed: int,
    expected_samples: int,
    expected_invalid_draw_policy: str,
) -> JSONObject:
    result = _response_result(response)
    input_digest = result.get("input_digest")
    if not isinstance(input_digest, str) or not _DIGEST_PATTERN.fullmatch(input_digest):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental uncertainty response did not include its input digest",
            retryable=False,
            status_code=502,
        )
    if input_digest != expected_input_digest:
        raise FundamentalServiceFailure(
            "INPUT_DIGEST_MISMATCH",
            "Fundamental uncertainty response is bound to a different caller input",
            retryable=False,
            status_code=502,
        )
    base = result.get("base")
    if not isinstance(base, Mapping):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental uncertainty response did not include its base calculation",
            retryable=False,
            status_code=502,
        )
    base_references = base.get("artifact_references")
    uncertainty_references = result.get("artifact_references")
    if (
        result.get("status") not in _QUALITY_STATUSES
        or not isinstance(base_references, list | tuple)
        or not isinstance(uncertainty_references, list | tuple)
        or not base_references
        or not uncertainty_references
        or any(
            not isinstance(reference, Mapping)
            or not isinstance(reference.get("artifact_id"), str)
            or not reference.get("artifact_id")
            or not isinstance(reference.get("content_hash"), str)
            or not _DIGEST_PATTERN.fullmatch(reference["content_hash"])
            or reference.get("artifact_type")
            not in {"calculation_evidence", "uncertainty_evidence"}
            for reference in (*base_references, *uncertainty_references)
        )
        or not any(
            reference.get("artifact_type") == "calculation_evidence"
            for reference in base_references
            if isinstance(reference, Mapping)
        )
        or not any(
            reference.get("artifact_type") == "uncertainty_evidence"
            for reference in base_references
            if isinstance(reference, Mapping)
        )
        or not any(
            reference.get("artifact_type") == "uncertainty_evidence"
            for reference in uncertainty_references
            if isinstance(reference, Mapping)
        )
        or any(
            not any(
                _payload_equal(reference, base_reference)
                for base_reference in base_references
            )
            for reference in uncertainty_references
        )
        or any(
            not any(
                _payload_equal(reference, uncertainty_reference)
                for uncertainty_reference in uncertainty_references
            )
            for reference in base_references
            if isinstance(reference, Mapping)
            and reference.get("artifact_type") == "uncertainty_evidence"
        )
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental uncertainty response did not bind its calculation and "
            "uncertainty evidence references",
            retryable=False,
            status_code=502,
        )
    requested_samples = result.get("requested_samples")
    valid_samples = result.get("valid_samples")
    invalid_samples = result.get("invalid_samples")
    if (
        result.get("seed") != expected_seed
        or requested_samples != expected_samples
        or result.get("invalid_draw_policy") != expected_invalid_draw_policy
        or result.get("sampler_version") != "python-random-v1"
        or not isinstance(valid_samples, int)
        or not isinstance(invalid_samples, int)
        or valid_samples < 0
        or invalid_samples < 0
        or valid_samples + invalid_samples != expected_samples
    ):
        raise FundamentalServiceFailure(
            "INPUT_UNCERTAINTY_CHANGED",
            "Fundamental service uncertainty summary changed caller controls",
            retryable=False,
            status_code=502,
        )
    return _narrow_result(result)


def _narrow_result(result: Mapping[str, object]) -> JSONObject:
    projection: JSONObject = {}
    for field in _PROJECTION_FIELDS:
        if field in result:
            projection[field] = result[field]
    base = result.get("base")
    if isinstance(base, Mapping):
        projection["base"] = _narrow_result(base)
    return projection


def _required_fact_fields(input_payload: Mapping[str, object]) -> tuple[str, ...]:
    """Keep the service-owned normalized field selection through resolution."""

    selector = input_payload.get("snapshot_selector")
    source = selector if isinstance(selector, Mapping) else input_payload
    fields = source.get("required_fields")
    if fields is None:
        fields = input_payload.get("historical_facts")
    if not isinstance(fields, list | tuple) or not fields:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "valuation input did not include required fact fields",
            retryable=False,
            status_code=502,
        )
    if any(not isinstance(field, str) or not field for field in fields):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "valuation input fact fields must be non-empty strings",
            retryable=False,
            status_code=502,
        )
    if len(set(fields)) != len(fields):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "valuation input fact fields must be unique",
            retryable=False,
            status_code=502,
        )
    return tuple(fields)


def _facts_projection(
    result: FundamentalFactsReadResultV1,
    *,
    expected_snapshot_id: str,
    expected_snapshot_manifest_digest: str,
    expected_fact_ids: tuple[str, ...],
) -> JSONObject:
    actual_fact_ids = tuple(fact.fact_id for fact in result.facts)
    if (
        result.snapshot_id != expected_snapshot_id
        or result.snapshot_manifest_digest != expected_snapshot_manifest_digest
        or len(actual_fact_ids) != len(set(actual_fact_ids))
        or set(expected_fact_ids) != set(actual_fact_ids)
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts response is not bound to the selected snapshot",
            retryable=False,
            status_code=502,
        )
    projection = result.model_dump(mode="json")
    projection["fact_ids"] = list(actual_fact_ids)
    return projection


def _timestamp_utc(value: object, *, context: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                f"{context} must be an ISO-8601 timestamp",
                retryable=False,
                status_code=502,
            ) from error
    else:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            f"{context} must be an ISO-8601 timestamp",
            retryable=False,
            status_code=502,
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            f"{context} must include a timezone",
            retryable=False,
            status_code=502,
        )
    return parsed.astimezone(UTC)


async def _facts_only_projection(
    prepared: PreparedServiceValuation,
    *,
    client: FundamentalServiceClient,
    principal: InternalPrincipal,
    correlation_id: str,
    deadline_at: datetime,
) -> JSONObject:
    selector = prepared.snapshot_selector
    selection_response = await client.execute(
        "resolve_snapshot",
        selector,
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    selection = _response_result(selection_response)
    snapshot_id = selection.get("snapshot_id")
    fact_ids = selection.get("historical_facts")
    identity = selection.get("identity")
    selected_at = selection.get("valuation_timestamp")
    provenance_raw = selection.get("provenance")
    release_digest = selection.get("data_release_manifest_digest")
    if (
        selection.get("contract_version") != "fundamental.v1"
        or not isinstance(snapshot_id, str)
        or not snapshot_id
        or not isinstance(fact_ids, list | tuple)
        or not fact_ids
        or any(not isinstance(fact_id, str) or not fact_id for fact_id in fact_ids)
        or len(set(fact_ids)) != len(fact_ids)
        or not isinstance(identity, Mapping)
        or not _payload_equal(identity, prepared.identity)
        or selection.get("source_selection_policy")
        != selector.get("source_selection_policy")
        or selection.get("coverage_profile") != selector.get("coverage_profile")
        or selection.get("quality") != "verified"
        or not isinstance(provenance_raw, Mapping)
        or not isinstance(provenance_raw.get("policy_version"), str)
        or not provenance_raw["policy_version"]
        or (release_digest is not None and not isinstance(release_digest, str))
        or (
            isinstance(release_digest, str)
            and not _DIGEST_PATTERN.fullmatch(release_digest)
        )
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts selection is incomplete or not bound to its identity",
            retryable=False,
            status_code=502,
        )
    selection_digest = selection.get("snapshot_manifest_digest")
    provenance_digest = provenance_raw.get("snapshot_manifest_digest")
    if provenance_raw.get("snapshot_id") not in (None, snapshot_id) or (
        selection_digest is not None
        and provenance_digest is not None
        and selection_digest != provenance_digest
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts selection provenance does not match its snapshot",
            retryable=False,
            status_code=502,
        )
    expected_snapshot_digest = selection_digest or provenance_digest
    if expected_snapshot_digest is not None and (
        not isinstance(expected_snapshot_digest, str)
        or not _DIGEST_PATTERN.fullmatch(expected_snapshot_digest)
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts selection returned an invalid snapshot digest",
            retryable=False,
            status_code=502,
        )
    selected_timestamp = _timestamp_utc(
        selected_at, context="Fundamental facts selection valuation_timestamp"
    )
    requested_timestamp = _timestamp_utc(
        selector.get("valuation_timestamp"),
        context="Fundamental facts selector valuation_timestamp",
    )
    if selected_timestamp != requested_timestamp:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts selection changed the point-in-time timestamp",
            retryable=False,
            status_code=502,
        )

    required_fields = selector.get("required_fields")
    if not isinstance(required_fields, list | tuple) or not required_fields:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts selector omitted required fields",
            retryable=False,
            status_code=502,
        )
    facts_result = await client.read_facts(
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": snapshot_id,
            "data_release_manifest_digest": release_digest,
            "required_fields": list(required_fields),
        },
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    if (
        not _payload_equal(
            facts_result.identity.model_dump(mode="json"), prepared.identity
        )
        or _timestamp_utc(
            facts_result.valuation_timestamp,
            context="Fundamental facts valuation_timestamp",
        )
        != selected_timestamp
        or facts_result.data_release_manifest_digest != release_digest
        or (
            expected_snapshot_digest is not None
            and facts_result.snapshot_manifest_digest != expected_snapshot_digest
        )
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental facts response changed the selected snapshot context",
            retryable=False,
            status_code=502,
        )
    facts = _facts_projection(
        facts_result,
        expected_snapshot_id=snapshot_id,
        expected_snapshot_manifest_digest=facts_result.snapshot_manifest_digest,
        expected_fact_ids=tuple(fact_ids),
    )
    source_hashes = sorted({fact.source.content_hash for fact in facts_result.facts})
    provenance = {
        key: value for key, value in provenance_raw.items() if value is not None
    }
    provenance.update({"snapshot_id": snapshot_id, "fact_ids": list(fact_ids)})
    hashes: JSONObject = {
        "snapshot_manifest_digest": facts_result.snapshot_manifest_digest,
        "source_content_hashes": source_hashes,
    }
    if release_digest is not None:
        hashes["data_release_manifest_digest"] = release_digest
    return {
        "contract_version": "fundamental.v1",
        "projection_type": "facts_only",
        "valuation_status": "not_requested",
        "snapshot_id": snapshot_id,
        "snapshot_manifest_digest": facts_result.snapshot_manifest_digest,
        "fact_ids": list(fact_ids),
        "facts": facts,
        "snapshot_selector": dict(selector),
        "provenance": provenance,
        "quality": {
            "facts_status": facts_result.quality_status,
            "issue_codes": list(facts_result.issue_codes),
        },
        "hashes": hashes,
        "issue_codes": list(facts_result.issue_codes),
    }


def _service_valuation_artifact_payload(
    *,
    projection: Mapping[str, object],
    input_payload: Mapping[str, object],
    input_digest: str,
    validation_quality_status: str,
    calculation_trace: Mapping[str, object],
) -> JSONObject:
    facts = _as_mapping(projection.get("facts"), context="fundamental facts projection")
    provenance = _as_mapping(
        input_payload["provenance"], context="validated_input.provenance"
    )
    quality = _as_mapping(input_payload["quality"], context="validated_input.quality")
    snapshot_id = facts.get("snapshot_id")
    snapshot_manifest_digest = facts.get("snapshot_manifest_digest")
    fact_ids = facts.get("fact_ids")
    if (
        not isinstance(snapshot_id, str)
        or not isinstance(snapshot_manifest_digest, str)
        or not isinstance(fact_ids, list | tuple)
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental artifact projection is missing snapshot metadata",
            retryable=False,
            status_code=502,
        )
    artifact_projection = dict(projection)
    artifact_projection.update(
        {
            "projection_type": "valuation",
            "contract_version": "fundamental.v1",
            "snapshot_id": snapshot_id,
            "snapshot_manifest_digest": snapshot_manifest_digest,
            "fact_ids": list(fact_ids),
            "valuation_trace": dict(calculation_trace),
            "provenance": dict(provenance),
            "quality": {
                "input": dict(quality),
                "validation_status": validation_quality_status,
                "facts_status": facts.get("quality_status"),
                "calculation_status": projection.get("quality_status"),
                "issue_codes": facts.get("issue_codes", ()),
            },
            "hashes": {
                "input_digest": input_digest,
                "result_hash": projection.get("result_hash"),
                "snapshot_manifest_digest": snapshot_manifest_digest,
                "data_release_manifest_digest": facts.get(
                    "data_release_manifest_digest"
                ),
                "source_content_hashes": calculation_trace.get(
                    "source_content_hashes", ()
                ),
            },
            "valuation_input": dict(input_payload),
        }
    )
    return {
        "financial_reports": [],
        "fundamental_service": artifact_projection,
        "status": "done",
        "model_type": input_payload.get("model_id"),
        "ticker": _ticker_from_input(input_payload),
    }


def _calculation_projection(
    response: FundamentalServiceResponseV1,
    *,
    expected_input_digest: str,
    expected_model_id: str,
    expected_model_version: str,
    expected_policy_id: str,
    expected_policy_version: str,
    expected_policy_digest: str,
    expected_source_selection_policy: str,
    expected_source_selection_policy_version: str | None,
    expected_snapshot_id: str,
    expected_fact_ids: tuple[str, ...],
    expected_assumptions: Mapping[str, object],
    expect_uncertainty_report: bool,
) -> JSONObject:
    result = _response_result(response)
    report_base = result.get("base")
    is_uncertainty_report = isinstance(report_base, Mapping)
    if is_uncertainty_report != expect_uncertainty_report:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not match requested uncertainty mode",
            retryable=False,
            status_code=502,
        )
    primary = report_base if is_uncertainty_report else result
    if not isinstance(primary, Mapping):  # pragma: no cover - guarded above
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response is invalid",
            retryable=False,
            status_code=502,
        )
    calculation_input_digest = primary.get("input_digest")
    result_hash = primary.get("result_hash")
    if not isinstance(calculation_input_digest, str) or not _DIGEST_PATTERN.fullmatch(
        calculation_input_digest
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include input_digest",
            retryable=False,
            status_code=502,
        )
    if is_uncertainty_report:
        report_input_digest = result.get("input_digest")
        if not isinstance(report_input_digest, str) or not _DIGEST_PATTERN.fullmatch(
            report_input_digest
        ):
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                "Fundamental uncertainty report did not include its caller input digest",
                retryable=False,
                status_code=502,
            )
        if report_input_digest != expected_input_digest:
            raise FundamentalServiceFailure(
                "INPUT_DIGEST_MISMATCH",
                "Fundamental uncertainty report is bound to a different caller input",
                retryable=False,
                status_code=502,
            )
    elif calculation_input_digest != expected_input_digest:
        raise FundamentalServiceFailure(
            "INPUT_DIGEST_MISMATCH",
            "Fundamental calculation response is bound to a different input",
            retryable=False,
            status_code=502,
        )
    if not isinstance(result_hash, str) or not _DIGEST_PATTERN.fullmatch(result_hash):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include result_hash",
            retryable=False,
            status_code=502,
        )
    calculation_version = primary.get("calculation_version")
    model_version = primary.get("model_version")
    policy_id = primary.get("policy_id")
    policy_version = primary.get("policy_version")
    snapshot_id = primary.get("snapshot_id")
    policy_resolution = primary.get("policy_resolution")
    if (
        not isinstance(calculation_version, str)
        or not calculation_version
        or model_version != expected_model_version
        or policy_id != expected_policy_id
        or policy_version != expected_policy_version
        or snapshot_id != expected_snapshot_id
        or not isinstance(policy_resolution, Mapping)
        or policy_resolution.get("contract_version") != "fundamental.v1"
        or policy_resolution.get("policy_id") != expected_policy_id
        or policy_resolution.get("policy_version") != expected_policy_version
        or policy_resolution.get("policy_digest") != expected_policy_digest
        or policy_resolution.get("input_digest") != calculation_input_digest
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response is missing or changed its "
            "version-bound provenance",
            retryable=False,
            status_code=502,
        )
    assumptions = primary.get("assumptions")
    if not isinstance(assumptions, Mapping) or not _caller_values_preserved(
        expected_assumptions, assumptions, path=("assumptions",)
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response changed caller assumptions",
            retryable=False,
            status_code=502,
        )
    trace = primary.get("trace")
    trace_fact_ids = trace.get("fact_ids") if isinstance(trace, Mapping) else None
    trace_source_hashes = (
        trace.get("source_content_hashes") if isinstance(trace, Mapping) else None
    )
    if (
        not isinstance(trace, Mapping)
        or trace.get("source_selection_policy") != expected_source_selection_policy
        or not isinstance(trace.get("source_selection_policy_version"), str)
        or not trace.get("source_selection_policy_version")
        or (
            expected_source_selection_policy_version is not None
            and trace.get("source_selection_policy_version")
            != expected_source_selection_policy_version
        )
        or trace.get("snapshot_id") != expected_snapshot_id
        or not isinstance(trace.get("snapshot_manifest_digest"), str)
        or not _DIGEST_PATTERN.fullmatch(trace["snapshot_manifest_digest"])
        or not isinstance(trace_fact_ids, list | tuple)
        or tuple(sorted(trace_fact_ids)) != tuple(sorted(expected_fact_ids))
        or not isinstance(trace_source_hashes, list | tuple)
        or not trace_source_hashes
        or any(
            not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value)
            for value in trace_source_hashes
        )
        or trace.get("policy_id") != expected_policy_id
        or trace.get("policy_version") != expected_policy_version
        or trace.get("policy_digest") != expected_policy_digest
        or trace.get("model_id") != expected_model_id
        or trace.get("model_version") != expected_model_version
        or not isinstance(trace.get("assumptions_digest"), str)
        or not _DIGEST_PATTERN.fullmatch(trace["assumptions_digest"])
        or trace.get("calculation_version") != calculation_version
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include complete "
            "version-bound evidence",
            retryable=False,
            status_code=502,
        )
    artifact_references = primary.get("artifact_references")
    allowed_artifact_types = {"calculation_evidence"}
    if is_uncertainty_report:
        allowed_artifact_types.add("uncertainty_evidence")
    if (
        not isinstance(artifact_references, list | tuple)
        or not artifact_references
        or any(
            not isinstance(reference, Mapping)
            or not isinstance(reference.get("artifact_id"), str)
            or not reference.get("artifact_id")
            or not isinstance(reference.get("content_hash"), str)
            or not _DIGEST_PATTERN.fullmatch(reference["content_hash"])
            or reference.get("artifact_type") not in allowed_artifact_types
            for reference in artifact_references
        )
        or not any(
            reference.get("artifact_type") == "calculation_evidence"
            for reference in artifact_references
            if isinstance(reference, Mapping)
        )
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include content-addressed "
            "artifact references",
            retryable=False,
            status_code=502,
        )
    calculation_status = primary.get("calculation_status")
    quality_status = primary.get("quality_status")
    if not isinstance(calculation_status, str) or not calculation_status:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include calculation_status",
            retryable=False,
            status_code=502,
        )
    if not isinstance(quality_status, str) or not quality_status:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include quality_status",
            retryable=False,
            status_code=502,
        )
    return {
        "calculation_version": calculation_version,
        "calculation_status": calculation_status,
        "quality_status": quality_status,
        "input_digest": expected_input_digest,
        "result_hash": result_hash,
        "service_result": _narrow_result(result),
        "correlation_id": response.correlation_id,
    }


def _service_error_update(
    *,
    fundamental: Mapping[str, object],
    error: Exception,
) -> FundamentalNodeResult:
    code = getattr(error, "code", "fundamental_service_unavailable")
    retryable = bool(getattr(error, "retryable", False))
    message = str(error)
    updated: FundamentalAnalysisContext = dict(fundamental)
    updated.update(
        {
            "valuation_status": "service_unavailable",
            "quality_status": "degraded",
            "service_failure": {"code": code, "retryable": retryable},
        }
    )
    return FundamentalNodeResult(
        update={
            "fundamental_analysis": updated,
            "active_activity_id": "calculation",
            "workflow_activity_updates": {"calculation": "error"},
            "error_logs": [
                {"node": "calculation", "error": message, "severity": "error"}
            ],
        },
        goto="END",
    )


async def run_service_valuation_flow(
    runtime: ServiceValuationRuntime,
    state: Mapping[str, object],
    *,
    client: FundamentalServiceClient,
    request_approval_fn: Callable[[JSONObject], object],
    timeout_seconds: float = FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
    clock: Callable[[], datetime] | None = None,
) -> FundamentalNodeResult:
    fundamental_raw = state.get("fundamental_analysis", {})
    fundamental = _as_mapping(fundamental_raw, context="fundamental_analysis")
    try:
        raw_request = state.get("valuation_request")
        if raw_request is None:
            raw_request = fundamental.get(_SERVICE_INPUT_KEY)
        input_payload: JSONObject | None = None
        if raw_request is not None:
            input_payload = read_service_valuation_input(state)
            request_timing = FundamentalRequestTimingV1.accept(
                input_payload, clock=clock
            )
            input_payload = apply_request_timing(input_payload, request_timing)
        else:
            request_timing = FundamentalRequestTimingV1.accept({}, clock=clock)
        fundamental = {
            **fundamental,
            "request_timing": request_timing.model_dump(mode="json"),
        }
        principal = get_request_principal()
        if principal is None:
            raise FundamentalServiceFailure(
                "AUTHENTICATION_FAILED",
                "authenticated Fundamental service principal is required",
                retryable=False,
                status_code=401,
            )
        correlation_id = resolve_correlation_id()
        deadline_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
        if input_payload is None:
            prepared = await prepare_service_valuation_request(
                state,
                client=client,
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
                request_timing=request_timing,
            )
            if prepared.valuation_request is None:
                facts_projection = await _facts_only_projection(
                    prepared,
                    client=client,
                    principal=principal,
                    correlation_id=correlation_id,
                    deadline_at=deadline_at,
                )
                ticker = prepared.identity.get("security_id")
                issuer_name = prepared.identity.get("issuer_name")
                model_type = fundamental.get("model_type")
                if not all(
                    isinstance(value, str) and value
                    for value in (ticker, issuer_name, model_type)
                ):
                    raise FundamentalServiceFailure(
                        "UPSTREAM_MALFORMED",
                        "Fundamental facts artifact is missing company display metadata",
                        retryable=False,
                        status_code=502,
                    )
                artifact_payload: JSONObject = {
                    "financial_reports": [],
                    "fundamental_service": facts_projection,
                    "status": "done",
                    "ticker": ticker,
                    "company_name": issuer_name,
                    "model_type": model_type,
                }
                try:
                    artifact_id = await runtime.save_financial_reports(
                        data=artifact_payload,
                        produced_by="fundamental_analysis.service_facts",
                        key_prefix="fundamental_service_facts",
                    )
                except Exception as exc:
                    raise FundamentalServiceFailure(
                        "ARTIFACT_SAVE_FAILED",
                        "Fundamental service facts artifact could not be saved",
                        retryable=True,
                        status_code=503,
                    ) from exc
                updated = dict(fundamental)
                updated.pop("service_failure", None)
                updated.update(
                    {
                        "valuation_status": "not_requested",
                        "quality_status": facts_projection["quality"]["facts_status"],
                        "fundamental_service": facts_projection,
                    }
                )
                return FundamentalNodeResult(
                    update={
                        "fundamental_analysis": updated,
                        "artifact_references": {
                            "financial_reports": to_artifact_reference_payload(
                                ArtifactReference(
                                    artifact_id=artifact_id,
                                    download_url=f"/api/v1/artifacts/{artifact_id}",
                                    type=ARTIFACT_KIND_FINANCIAL_REPORTS,
                                )
                            )
                        },
                        "active_activity_id": "calculation",
                        "workflow_activity_updates": {"calculation": "done"},
                    },
                    goto="END",
                )
            input_payload = prepared.valuation_request
        assert input_payload is not None
        required_fact_fields = _required_fact_fields(input_payload)
        selector = input_payload.get("snapshot_selector")
        source_selection_policy_version: str | None = None
        if selector is not None:
            if not isinstance(selector, Mapping):
                raise ValueError(
                    "valuation_request.snapshot_selector must be an object"
                )
            resolution_response = await client.execute(
                "resolve_snapshot",
                selector,
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            input_payload, source_selection_policy_version = _resolved_snapshot_input(
                input_payload, _response_result(resolution_response)
            )
        validation_response = await client.execute(
            "validate",
            input_payload,
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
        )
        validation_result = _response_result(validation_response)
        (
            validated_input,
            input_digest,
            quality_status,
            policy_resolution,
        ) = _validated_input(validation_result)
        if not _caller_values_preserved(
            input_payload.get("assumptions"),
            validated_input.get("assumptions"),
            path=("assumptions",),
        ):
            raise FundamentalServiceFailure(
                "INPUT_ASSUMPTIONS_CHANGED",
                "Fundamental service changed caller-supplied assumptions",
                retryable=False,
                status_code=502,
            )
        if not _caller_values_preserved(
            input_payload.get("uncertainty"),
            validated_input.get("uncertainty"),
            path=("uncertainty",),
        ):
            raise FundamentalServiceFailure(
                "INPUT_UNCERTAINTY_CHANGED",
                "Fundamental service changed caller-supplied uncertainty controls",
                retryable=False,
                status_code=502,
            )
    except (FundamentalServiceFailure, ValueError, TypeError) as error:
        return _service_error_update(fundamental=fundamental, error=error)

    approval_request = _approval_request(
        input_payload=validated_input,
        input_digest=input_digest,
        quality_status=quality_status,
        validation_result=validation_result,
    )
    approval_response = request_approval_fn(approval_request)
    if not _approval_is_accepted(approval_response):
        return _service_error_update(
            fundamental=fundamental,
            error=ValueError("valuation approval response has an invalid contract"),
        )
    if approval_response["decision"] == "reject":
        updated = dict(fundamental)
        updated.update(
            {
                "valuation_status": "approval_rejected",
                "quality_status": quality_status,
                "input_digest": input_digest,
            }
        )
        return FundamentalNodeResult(
            update={
                "fundamental_analysis": updated,
                "active_activity_id": "calculation",
                "workflow_activity_updates": {"calculation": "done"},
            },
            goto="END",
        )

    approved_input = dict(validated_input)
    approved_input["input_digest"] = input_digest
    approved_input["caller_approval"] = {
        "input_digest": input_digest,
        "decision": "approved",
        "caller_id": principal.subject_id,
        "decided_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    try:
        calculation_response = await client.execute(
            "calculate",
            approved_input,
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
        )
        valuation_context = _as_mapping(
            validated_input["valuation_context"],
            context="validated_input.valuation_context",
        )
        provenance = _as_mapping(
            validated_input["provenance"], context="validated_input.provenance"
        )
        model_id = validated_input.get("model_id")
        model_version = validated_input.get("model_version")
        policy_id = validated_input.get("policy_id")
        policy_version = provenance.get("policy_version")
        policy_digest = policy_resolution.get("policy_digest")
        snapshot_id = valuation_context.get("data_snapshot_id")
        source_selection_policy = valuation_context.get("source_selection_policy")
        fact_ids = validated_input.get("historical_facts")
        if (
            not all(
                isinstance(value, str) and value
                for value in (
                    model_id,
                    model_version,
                    policy_id,
                    policy_version,
                    policy_digest,
                    snapshot_id,
                    source_selection_policy,
                )
            )
            or not isinstance(fact_ids, list | tuple)
            or not fact_ids
            or any(not isinstance(value, str) or not value for value in fact_ids)
        ):
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                "validated Fundamental input is missing model, policy, or snapshot "
                "version metadata",
                retryable=False,
                status_code=502,
            )
        uncertainty = _as_mapping(
            validated_input["uncertainty"], context="validated_input.uncertainty"
        )
        expect_uncertainty_report = uncertainty.get("mode") == "monte_carlo"
        projection = _calculation_projection(
            calculation_response,
            expected_input_digest=input_digest,
            expected_model_id=model_id,
            expected_model_version=model_version,
            expected_policy_id=policy_id,
            expected_policy_version=policy_version,
            expected_policy_digest=policy_digest,
            expected_source_selection_policy=source_selection_policy,
            expected_source_selection_policy_version=source_selection_policy_version,
            expected_snapshot_id=snapshot_id,
            expected_fact_ids=tuple(fact_ids),
            expected_assumptions=_as_mapping(
                validated_input["assumptions"],
                context="validated_input.assumptions",
            ),
            expect_uncertainty_report=expect_uncertainty_report,
        )
        service_result = _as_mapping(
            projection["service_result"], context="fundamental calculation result"
        )
        primary_result = service_result.get("base", service_result)
        primary_result = _as_mapping(
            primary_result, context="fundamental calculation primary result"
        )
        calculation_trace = _as_mapping(
            primary_result.get("trace"),
            context="fundamental calculation trace",
        )
        valuation_context = _as_mapping(
            validated_input["valuation_context"],
            context="validated_input.valuation_context",
        )
        facts_result = await client.read_facts(
            {
                "contract_version": "fundamental.v1",
                "snapshot_id": snapshot_id,
                "data_release_manifest_digest": valuation_context.get(
                    "data_release_manifest_digest"
                ),
                "required_fields": list(required_fact_fields),
            },
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
        )
        snapshot_manifest_digest = calculation_trace.get("snapshot_manifest_digest")
        if not isinstance(
            snapshot_manifest_digest, str
        ) or not _DIGEST_PATTERN.fullmatch(snapshot_manifest_digest):
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                "Fundamental calculation trace omitted snapshot manifest digest",
                retryable=False,
                status_code=502,
            )
        projection["facts"] = _facts_projection(
            facts_result,
            expected_snapshot_id=snapshot_id,
            expected_snapshot_manifest_digest=snapshot_manifest_digest,
            expected_fact_ids=tuple(fact_ids),
        )
        if expect_uncertainty_report:
            samples = uncertainty.get("samples")
            seed = uncertainty.get("seed")
            invalid_draw_policy = uncertainty.get("invalid_draw_policy")
            if (
                not isinstance(snapshot_id, str)
                or not isinstance(samples, int)
                or not isinstance(seed, int)
                or not isinstance(invalid_draw_policy, str)
            ):
                raise FundamentalServiceFailure(
                    "UPSTREAM_MALFORMED",
                    "Validated Monte Carlo input omitted required caller controls",
                    retryable=False,
                    status_code=502,
                )
            projection["uncertainty_summary"] = _uncertainty_projection(
                calculation_response,
                expected_input_digest=input_digest,
                expected_seed=seed,
                expected_samples=samples,
                expected_invalid_draw_policy=invalid_draw_policy,
            )
        artifact_payload = _service_valuation_artifact_payload(
            projection=projection,
            input_payload=approved_input,
            input_digest=input_digest,
            validation_quality_status=quality_status,
            calculation_trace=calculation_trace,
        )
        try:
            artifact_id = await runtime.save_financial_reports(
                data=artifact_payload,
                produced_by="fundamental_analysis.service_valuation",
                key_prefix="fundamental_service_valuation",
            )
        except Exception as exc:
            raise FundamentalServiceFailure(
                "ARTIFACT_SAVE_FAILED",
                "Fundamental service valuation artifact could not be saved",
                retryable=True,
                status_code=503,
            ) from exc
    except (FundamentalServiceFailure, ValueError, TypeError) as error:
        return _service_error_update(fundamental=fundamental, error=error)

    updated = dict(fundamental)
    updated.update(
        {
            "valuation_status": projection["calculation_status"],
            "quality_status": projection["quality_status"],
            "input_digest": projection["input_digest"],
            "result_hash": projection["result_hash"],
            "fundamental_service": projection,
            "assumption_breakdown": {
                "source": "fundamental-service",
                "assumptions": approved_input["assumptions"],
                "uncertainty": approved_input["uncertainty"],
            },
        }
    )
    return FundamentalNodeResult(
        update={
            "fundamental_analysis": updated,
            "artifact_references": {
                "financial_reports": to_artifact_reference_payload(
                    ArtifactReference(
                        artifact_id=artifact_id,
                        download_url=f"/api/v1/artifacts/{artifact_id}",
                        type=ARTIFACT_KIND_FINANCIAL_REPORTS,
                    )
                )
            },
            "active_activity_id": "calculation",
            "workflow_activity_updates": {"calculation": "done"},
        },
        goto="END",
    )


__all__ = [
    "read_service_valuation_input",
    "run_service_valuation_flow",
]
