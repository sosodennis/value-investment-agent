"""Prepare Fundamental inputs from authenticated released evidence."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ConfigDict, JsonValue, TypeAdapter

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalReleaseSelector,
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.valuation_revision_port import (
    FundamentalRevisionSourceReaderPort,
)
from src.agents.fundamental.application.workflow_orchestrator.services.valuation_revision import (
    prepare_retained_valuation_revision,
)
from src.agents.fundamental.application.workflow_orchestrator.state_readers import (
    read_intent_state,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalIdentityResolutionRequestV1,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalRequestTimingV1,
    FundamentalValuationIntentV1,
)
from src.shared.artifacts.fundamental_contracts import (
    FundamentalValuationPreparationResultV1,
)
from src.shared.internal_services import InternalPrincipal
from src.shared.kernel.types import JSONObject

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_JSON_OBJECT = TypeAdapter[JSONObject](
    dict[str, JsonValue], config=ConfigDict(allow_inf_nan=False)
)
_SUPPORTED_MODELS = {"fcff_dcf", "transition_fcff_dcf"}
_MODEL_BY_SELECTION = {
    "dcf_standard": "fcff_dcf",
    "dcf_growth": "transition_fcff_dcf",
}


@dataclass(frozen=True)
class PreparedServiceValuation:
    """Service evidence plus an optional complete caller valuation request."""

    valuation_request: JSONObject | None
    identity: JSONObject
    release_manifest_digest: str
    snapshot_selector: JSONObject
    preparation: FundamentalValuationPreparationResultV1 | None = None
    reason: str | None = None


def _mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            f"{context} must be an object",
            retryable=False,
            status_code=502,
        )
    return value


def _json_object(value: Mapping[str, object], *, context: str) -> JSONObject:
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except (TypeError, ValueError) as error:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            f"{context} must contain only JSON values",
            retryable=False,
            status_code=502,
        ) from error


def _timestamp(value: object) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if not isinstance(value, str):
        raise FundamentalServiceFailure(
            "VALUATION_INPUT_INVALID",
            "valuation_timestamp must be an ISO-8601 string",
            retryable=False,
            status_code=422,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise FundamentalServiceFailure(
            "VALUATION_INPUT_INVALID",
            "valuation_timestamp must be a valid ISO-8601 string",
            retryable=False,
            status_code=422,
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FundamentalServiceFailure(
            "VALUATION_INPUT_INVALID",
            "valuation_timestamp must include a timezone",
            retryable=False,
            status_code=422,
        )
    return parsed.astimezone(UTC)


def _model_id(
    request: Mapping[str, object] | None,
    fundamental: Mapping[str, object],
) -> str:
    if request is None:
        return "fcff_dcf"
    candidate = request.get("model_id") if request is not None else None
    if not isinstance(candidate, str) or not candidate:
        selection = fundamental.get("model_type")
        candidate = (
            _MODEL_BY_SELECTION.get(selection) if isinstance(selection, str) else None
        )
    if not isinstance(candidate, str) or candidate not in _SUPPORTED_MODELS:
        raise FundamentalServiceFailure(
            "VALUATION_MODEL_UNAVAILABLE",
            "Fundamental service request requires a released FCFF model",
            retryable=False,
            status_code=422,
        )
    return candidate


def is_compact_valuation_request(value: Mapping[str, object]) -> bool:
    """Return whether a request contains caller inputs but no service evidence."""

    return not {
        "identity",
        "valuation_context",
        "quality",
        "provenance",
    }.intersection(value)


def _explicit_fiscal_period_selector(
    request: Mapping[str, object],
) -> JSONObject | None:
    selector = request.get("fiscal_period_selector")
    if selector is None:
        context = request.get("valuation_context")
        if isinstance(context, Mapping):
            selector = context.get("fiscal_period_selector")
    return dict(selector) if isinstance(selector, Mapping) else None


def _preparation_selection(
    result: object,
    *,
    identity: JSONObject,
    valuation_timestamp: datetime,
) -> tuple[str, str]:
    """Extract the immutable snapshot and active release for preparation."""

    payload = _mapping(result, context="Fundamental snapshot resolution result")
    snapshot_id = payload.get("snapshot_id")
    release_digest = payload.get("data_release_manifest_digest")
    resolved_identity = payload.get("identity")
    resolved_timestamp = payload.get("valuation_timestamp")
    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id
        or not isinstance(release_digest, str)
        or not _DIGEST_PATTERN.fullmatch(release_digest)
        or not isinstance(resolved_identity, Mapping)
        or dict(resolved_identity) != identity
        or not isinstance(resolved_timestamp, str)
        or _timestamp(resolved_timestamp) != valuation_timestamp
    ):
        raise FundamentalServiceFailure(
            "SNAPSHOT_PREPARATION_UNAVAILABLE",
            "Fundamental snapshot resolution did not return a pinned release",
            retryable=False,
            status_code=422,
        )
    return snapshot_id, release_digest


def _prepared_input(
    result: FundamentalValuationPreparationResultV1,
    *,
    model_id: str,
    snapshot_id: str,
    release_digest: str,
    identity: JSONObject,
) -> JSONObject:
    """Validate only boundary bindings; valuation semantics stay service-owned."""

    if result.model_id != model_id:
        raise FundamentalServiceFailure(
            "PREPARATION_MODEL_MISMATCH",
            "Fundamental preparation returned a different model",
            retryable=False,
            status_code=502,
        )
    if result.status != "prepared" or result.input is None:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "prepared Fundamental result omitted its input",
            retryable=False,
            status_code=502,
        )
    prepared = _json_object(result.input, context="Fundamental preparation.input")
    prepared_identity = prepared.get("identity")
    context = prepared.get("valuation_context")
    if (
        not isinstance(prepared_identity, Mapping)
        or dict(prepared_identity) != identity
    ):
        raise FundamentalServiceFailure(
            "PREPARATION_IDENTITY_MISMATCH",
            "Fundamental preparation changed the resolved identity",
            retryable=False,
            status_code=502,
        )
    if not isinstance(context, Mapping):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental preparation omitted valuation context",
            retryable=False,
            status_code=502,
        )
    if (
        context.get("data_snapshot_id") != snapshot_id
        or context.get("data_release_manifest_digest") != release_digest
        or prepared.get("model_id") != model_id
        or prepared.get("model_version") != result.model_version
        or prepared.get("policy_id") != result.policy_id
    ):
        raise FundamentalServiceFailure(
            "PREPARATION_PROVENANCE_MISMATCH",
            "Fundamental preparation input is not bound to its pinned snapshot",
            retryable=False,
            status_code=502,
        )
    return prepared


async def prepare_service_valuation_request(
    state: Mapping[str, object],
    *,
    client: FundamentalServiceClient,
    principal: InternalPrincipal,
    correlation_id: str,
    deadline_at: datetime,
    request_timing: FundamentalRequestTimingV1 | None = None,
    release_selector: FundamentalReleaseSelector | None = None,
    revision_source_reader: FundamentalRevisionSourceReaderPort | None = None,
    current_thread_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PreparedServiceValuation:
    """Prepare automatic valuation or facts from a configured immutable release."""

    intent = read_intent_state(state)
    ticker = intent.resolved_ticker
    if ticker is None:
        raise FundamentalServiceFailure(
            "FUNDAMENTAL_TICKER_MISSING",
            "No resolved ticker available for Fundamental service identity resolution",
            retryable=False,
            status_code=422,
        )
    fundamental_raw = state.get("fundamental_analysis", {})
    fundamental = _mapping(fundamental_raw, context="fundamental_analysis")
    request_raw = state.get("valuation_request")
    if request_raw is None:
        request_raw = fundamental.get("valuation_request")
    request = (
        _mapping(request_raw, context="valuation_request")
        if request_raw is not None
        else None
    )
    compact = (
        FundamentalValuationIntentV1.model_validate(request)
        if request is not None and is_compact_valuation_request(request)
        else None
    )
    revision = compact.revision if compact is not None else None
    model_id = _model_id(request, fundamental) if revision is None else None
    if revision is None and release_selector is None:
        raise FundamentalServiceFailure(
            "SERVICE_NOT_CONFIGURED",
            "Fundamental release selection is not configured",
            retryable=False,
            status_code=503,
        )
    valuation_context = (
        _mapping(
            request.get("valuation_context"),
            context="valuation_request.valuation_context",
        )
        if request is not None and request.get("valuation_context") is not None
        else {}
    )
    valuation_timestamp = (
        request_timing.valuation_timestamp
        if request_timing is not None
        else _timestamp(
            valuation_context.get("valuation_timestamp")
            or (request.get("requested_as_of") if request is not None else None)
        )
    )
    explicit_fiscal_period_selector = (
        _explicit_fiscal_period_selector(request) if request is not None else None
    )
    fiscal_period_selector = (
        request_timing.fiscal_period_selector.model_dump(mode="json")
        if request_timing is not None and explicit_fiscal_period_selector is not None
        else None
    )

    resolution = await client.resolve_identity(
        FundamentalIdentityResolutionRequestV1(ticker=ticker),
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    if resolution.ticker != ticker:
        raise FundamentalServiceFailure(
            "IDENTITY_MISMATCH",
            "Fundamental identity resolver returned a different ticker",
            retryable=False,
            status_code=502,
        )
    identity = resolution.identity.model_dump(mode="json")
    if request is not None and request.get("identity") not in (None, identity):
        raise FundamentalServiceFailure(
            "IDENTITY_MISMATCH",
            "valuation_request identity does not match service resolution",
            retryable=False,
            status_code=422,
        )
    if revision is not None:
        assert compact is not None
        if revision_source_reader is None or current_thread_id is None:
            raise FundamentalServiceFailure(
                "REVISION_SOURCE_UNAVAILABLE",
                "Authenticated retained valuation source access is unavailable",
                retryable=False,
                status_code=503,
            )
        preparation = await prepare_retained_valuation_revision(
            revision,
            source_reader=revision_source_reader,
            current_thread_id=current_thread_id,
            requested_model_id=compact.model_id,
            requested_model_version=compact.model_version,
            requested_policy_id=compact.policy_id,
            identity=identity,
            client=client,
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
            modified_at=(clock or (lambda: datetime.now(UTC)))(),
        )
        context = _mapping(
            (preparation.input or {}).get("valuation_context"),
            context="Fundamental revised preparation valuation_context",
        )
        snapshot_id = context.get("data_snapshot_id")
        release_digest = context.get("data_release_manifest_digest")
        if not isinstance(snapshot_id, str) or not isinstance(release_digest, str):
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                "Fundamental revised preparation omitted its source bindings",
                retryable=False,
                status_code=502,
            )
        prepared = _prepared_input(
            preparation,
            model_id=preparation.model_id,
            snapshot_id=snapshot_id,
            release_digest=release_digest,
            identity=identity,
        )
        return PreparedServiceValuation(
            valuation_request=prepared,
            identity=identity,
            release_manifest_digest=release_digest,
            snapshot_selector={
                "snapshot_id": snapshot_id,
                "data_release_manifest_digest": release_digest,
            },
            preparation=preparation,
        )
    assert release_selector is not None
    assert model_id is not None
    cik = identity.get("issuer_id")
    if not isinstance(cik, str) or not cik.isdigit():
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental identity resolver returned an invalid issuer id",
            retryable=False,
            status_code=502,
        )
    release = await client.read_active_release(
        release_selector.profile_id,
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    if release.active.profile_id != release_selector.profile_id:
        raise FundamentalServiceFailure(
            "RELEASE_PROFILE_MISMATCH",
            "Fundamental release does not match the configured profile",
            retryable=False,
            status_code=502,
        )
    required_fields = release.manifest.required_fields
    snapshot_selector: JSONObject = {
        "contract_version": "fundamental.v1",
        "release_profile_id": release_selector.profile_id,
        "identity": identity,
        "valuation_timestamp": valuation_timestamp.isoformat().replace("+00:00", "Z"),
        **(
            {"fiscal_period_selector": fiscal_period_selector}
            if fiscal_period_selector is not None
            else {}
        ),
        "source_selection_policy": release_selector.source_selection_policy,
        "coverage_profile": release_selector.coverage_profile,
        "required_fields": list(required_fields),
    }
    if request is None:
        return PreparedServiceValuation(
            valuation_request=None,
            identity=identity,
            release_manifest_digest=release.active.manifest_digest,
            snapshot_selector=snapshot_selector,
            reason="caller valuation assumptions are required",
        )
    snapshot_response = await client.execute(
        "resolve_snapshot",
        snapshot_selector,
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    snapshot_id, release_digest = _preparation_selection(
        snapshot_response.result,
        identity=identity,
        valuation_timestamp=valuation_timestamp,
    )
    if release_digest != release.active.manifest_digest:
        raise FundamentalServiceFailure(
            "RELEASE_DIGEST_MISMATCH",
            "Active Fundamental release changed during snapshot selection",
            retryable=True,
            status_code=409,
        )
    preparation = await client.prepare_valuation(
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": snapshot_id,
            "data_release_manifest_digest": release_digest,
            "model_id": model_id,
        },
        principal=principal,
        correlation_id=correlation_id,
        deadline_at=deadline_at,
    )
    if preparation.status != "prepared":
        return PreparedServiceValuation(
            valuation_request=None,
            identity=identity,
            release_manifest_digest=release.active.manifest_digest,
            snapshot_selector=snapshot_selector,
            preparation=preparation,
            reason=preparation.status,
        )
    prepared = _prepared_input(
        preparation,
        model_id=model_id,
        snapshot_id=snapshot_id,
        release_digest=release_digest,
        identity=identity,
    )
    return PreparedServiceValuation(
        valuation_request=prepared,
        identity=identity,
        release_manifest_digest=release.active.manifest_digest,
        snapshot_selector=snapshot_selector,
        preparation=preparation,
    )


__all__ = [
    "PreparedServiceValuation",
    "is_compact_valuation_request",
    "prepare_service_valuation_request",
]
