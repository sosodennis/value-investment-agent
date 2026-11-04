"""Caller-owned orchestration for the Fundamental service cutover."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalServiceResponseV1,
)
from src.shared.internal_services import get_request_principal
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
_MONTE_CARLO_SAMPLER_VERSION = "python-random-v1"


class ServiceValuationRuntime(Protocol):
    def build_valuation_error_update(self, error: str) -> JSONObject: ...


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
    required_fields = _REQUIRED_INPUT_FIELDS - (
        {"historical_facts"} if has_selector else set()
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


def _validated_input(result: Mapping[str, object]) -> tuple[JSONObject, str, str]:
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
    return dict(raw_input), input_digest, quality_status


def _resolved_snapshot_input(
    input_payload: Mapping[str, object], result: Mapping[str, object]
) -> JSONObject:
    """Bind service-owned snapshot and fact references into the caller request."""

    snapshot_id = result.get("snapshot_id")
    facts = result.get("historical_facts")
    resolved_identity = result.get("identity")
    resolved_timestamp = result.get("valuation_timestamp")
    resolved_policy = result.get("source_selection_policy")
    resolved_profile = result.get("coverage_profile")
    provenance_raw = result.get("provenance")
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
        or not isinstance(provenance_raw, Mapping)
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
    }
    updated["provenance"] = {
        **provenance,
        **{key: value for key, value in provenance_raw.items() if value is not None},
        "snapshot_id": snapshot_id,
        "fact_ids": list(facts),
    }
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
    return updated


def _payload_equal(left: object, right: object) -> bool:
    """Compare JSON-shaped caller fields without changing their values."""

    try:
        return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
            right, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return left == right


def _caller_values_preserved(supplied: object, returned: object) -> bool:
    """Require caller values to survive typed contract normalization."""

    if isinstance(supplied, Mapping):
        return isinstance(returned, Mapping) and all(
            key in returned and _caller_values_preserved(value, returned[key])
            for key, value in supplied.items()
        )
    if isinstance(supplied, list | tuple):
        return (
            isinstance(returned, list | tuple)
            and len(supplied) == len(returned)
            and all(
                _caller_values_preserved(left, right)
                for left, right in zip(supplied, returned, strict=True)
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


def _monte_carlo_payload(input_payload: Mapping[str, object]) -> JSONObject:
    uncertainty = input_payload.get("uncertainty")
    if not isinstance(uncertainty, Mapping) or uncertainty.get("mode") != "monte_carlo":
        raise ValueError("Monte Carlo execution requires explicit caller controls")
    request: JSONObject = dict(input_payload)
    request["monte_carlo"] = {
        "uncertainty": dict(uncertainty),
        "sampler_version": _MONTE_CARLO_SAMPLER_VERSION,
    }
    return request


def _uncertainty_projection(
    response: FundamentalServiceResponseV1,
    *,
    snapshot_id: str,
    expected_seed: int,
    expected_samples: int,
    expected_invalid_draw_policy: str,
) -> JSONObject:
    result = _response_result(response)
    base = result.get("base")
    if not isinstance(base, Mapping):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental uncertainty response did not include its base calculation",
            retryable=False,
            status_code=502,
        )
    base_digest = base.get("input_digest")
    base_hash = base.get("result_hash")
    if (
        not isinstance(base_digest, str)
        or not _DIGEST_PATTERN.fullmatch(base_digest)
        or not isinstance(base_hash, str)
        or not _DIGEST_PATTERN.fullmatch(base_hash)
        or base.get("snapshot_id") != snapshot_id
    ):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental uncertainty base result is not traceable to the "
            "selected snapshot",
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
        or result.get("sampler_version") != _MONTE_CARLO_SAMPLER_VERSION
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


def _calculation_projection(
    response: FundamentalServiceResponseV1,
    *,
    expected_input_digest: str,
) -> JSONObject:
    result = _response_result(response)
    primary = result.get("base") if isinstance(result.get("base"), Mapping) else result
    if not isinstance(primary, Mapping):  # pragma: no cover - guarded above
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response is invalid",
            retryable=False,
            status_code=502,
        )
    input_digest = primary.get("input_digest")
    result_hash = primary.get("result_hash")
    if not isinstance(input_digest, str) or not _DIGEST_PATTERN.fullmatch(input_digest):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental calculation response did not include input_digest",
            retryable=False,
            status_code=502,
        )
    if input_digest != expected_input_digest:
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
        "calculation_status": calculation_status,
        "quality_status": quality_status,
        "input_digest": input_digest,
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
    timeout_seconds: float = 10.0,
) -> FundamentalNodeResult:
    fundamental_raw = state.get("fundamental_analysis", {})
    fundamental = _as_mapping(fundamental_raw, context="fundamental_analysis")
    try:
        input_payload = read_service_valuation_input(state)
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
        selector = input_payload.get("snapshot_selector")
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
            input_payload = _resolved_snapshot_input(
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
        validated_input, input_digest, quality_status = _validated_input(
            validation_result
        )
        if not _caller_values_preserved(
            input_payload.get("assumptions"), validated_input.get("assumptions")
        ):
            raise FundamentalServiceFailure(
                "INPUT_ASSUMPTIONS_CHANGED",
                "Fundamental service changed caller-supplied assumptions",
                retryable=False,
                status_code=502,
            )
        if not _caller_values_preserved(
            input_payload.get("uncertainty"), validated_input.get("uncertainty")
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
        projection = _calculation_projection(
            calculation_response,
            expected_input_digest=input_digest,
        )
        uncertainty = _as_mapping(
            validated_input["uncertainty"], context="validated_input.uncertainty"
        )
        if uncertainty.get("mode") == "monte_carlo":
            uncertainty_response = await client.execute(
                "uncertainty",
                _monte_carlo_payload(approved_input),
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
            valuation_context = _as_mapping(
                validated_input["valuation_context"],
                context="validated_input.valuation_context",
            )
            snapshot_id = valuation_context.get("data_snapshot_id")
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
                uncertainty_response,
                snapshot_id=snapshot_id,
                expected_seed=seed,
                expected_samples=samples,
                expected_invalid_draw_policy=invalid_draw_policy,
            )
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
            "active_activity_id": "calculation",
            "workflow_activity_updates": {"calculation": "done"},
        },
        goto="END",
    )


__all__ = [
    "read_service_valuation_input",
    "run_service_valuation_flow",
]
