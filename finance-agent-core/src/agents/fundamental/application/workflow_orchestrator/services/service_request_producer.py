"""Build service-owned SEC valuation inputs at the Fundamental boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.state_readers import (
    read_intent_state,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalIdentityResolutionRequestV1,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalRequestTimingV1,
)
from src.shared.internal_services import InternalPrincipal
from src.shared.kernel.types import JSONObject

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_MODELS = {"fcff_dcf", "transition_fcff_dcf"}
_MODEL_BY_SELECTION = {
    "dcf_standard": "fcff_dcf",
    "dcf_growth": "transition_fcff_dcf",
}
_MODEL_VERSION = {
    "fcff_dcf": "fcff_dcf-v1",
    "transition_fcff_dcf": "transition_fcff_dcf-v1",
}
_POLICY_ID = {
    "fcff_dcf": "fcff_dcf-us-gaap-public-v1",
    "transition_fcff_dcf": "transition_fcff_dcf-us-gaap-public-v1",
}
_BASE_REQUIRED_FIELDS = (
    "revenue",
    "operating_income",
    "cash",
    "debt",
    "diluted_shares",
)
_TRANSITION_REQUIRED_FIELDS = _BASE_REQUIRED_FIELDS + ("filed_operating_evidence",)
_INGESTION_POLICY = "sec-pit-v1"
_SNAPSHOT_POLICY = "pit-v1"
_DATA_RELEASE_PROFILE_ID = "sec-public-pit-v1"
_COVERAGE_PROFILE = "us-gaap-public-v1"
_LEGAL_USE_PROFILE = "sec-public-us-v1"
_PARSER_VERSION = "2.47.4"
_VALIDATION_PROFILE_ID = "sec-efm-us-dqc-v31.0.3"
_TAXONOMY_MANIFEST_ID = "sec-us-gaap-2023-2024-public-bundle"
_TAXONOMY_VERSION = "us-gaap-2023-2024"
_POLICY_VERSION = "sec-public-pit-v1"
_MAPPING_VERSION = "sec-us-gaap-v1"
_COMPACT_REQUEST_FIELDS = frozenset(
    {
        "contract_version",
        "model_id",
        "model_version",
        "policy_id",
        "assumptions",
        "uncertainty",
        "requested_as_of",
        "fiscal_period_selector",
    }
)


@dataclass(frozen=True)
class PreparedServiceValuation:
    """Service evidence plus an optional complete caller valuation request."""

    valuation_request: JSONObject | None
    identity: JSONObject
    ingestion: JSONObject
    snapshot_selector: JSONObject
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
    # Facts-only reports do not carry caller-owned assumptions, so they must
    # request only the base evidence set. Transition-only evidence belongs to
    # an explicit valuation request for the transition model.
    if request is None:
        return "fcff_dcf"
    candidate = request.get("model_id") if request is not None else None
    if not isinstance(candidate, str) or not candidate:
        candidate = _MODEL_BY_SELECTION.get(fundamental.get("model_type"))
    if candidate not in _SUPPORTED_MODELS:
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


def _normalize_compact_request(
    request: Mapping[str, object],
    *,
    model_id: str,
    valuation_context: Mapping[str, object],
    valuation_timestamp: datetime,
    fiscal_period_selector: JSONObject | None,
) -> JSONObject:
    unknown = sorted(set(request).difference(_COMPACT_REQUEST_FIELDS))
    if unknown:
        raise FundamentalServiceFailure(
            "VALUATION_INPUT_INVALID",
            "compact valuation request contains unsupported fields: "
            + ", ".join(unknown),
            retryable=False,
            status_code=422,
        )
    assumptions = request.get("assumptions")
    if not isinstance(assumptions, Mapping):
        raise FundamentalServiceFailure(
            "VALUATION_INPUT_INVALID",
            "compact valuation request requires caller-owned assumptions",
            retryable=False,
            status_code=422,
        )
    normalized: JSONObject = dict(request)
    normalized["contract_version"] = "fundamental.v1"
    normalized["model_id"] = model_id
    normalized["model_version"] = (
        normalized.get("model_version") or _MODEL_VERSION[model_id]
    )
    normalized["policy_id"] = normalized.get("policy_id") or _POLICY_ID[model_id]
    normalized["uncertainty"] = dict(normalized.get("uncertainty") or {"mode": "none"})
    normalized["quality"] = {"status": "verified"}
    normalized["provenance"] = {
        "snapshot_id": "pending",
        "fact_ids": [],
        "mapping_version": _MAPPING_VERSION,
        "parser_version": _PARSER_VERSION,
        "taxonomy_version": _TAXONOMY_VERSION,
        "policy_version": _POLICY_VERSION,
    }
    normalized["valuation_context"] = {
        **valuation_context,
        "valuation_timestamp": valuation_timestamp.isoformat().replace("+00:00", "Z"),
        **(
            {"fiscal_period_selector": fiscal_period_selector}
            if fiscal_period_selector is not None
            else {}
        ),
        "source_selection_policy": _SNAPSHOT_POLICY,
        "coverage_profile": _COVERAGE_PROFILE,
    }
    normalized.pop("input_digest", None)
    normalized.pop("caller_approval", None)
    return normalized


def _required_fields(model_id: str) -> tuple[str, ...]:
    return (
        _TRANSITION_REQUIRED_FIELDS
        if model_id == "transition_fcff_dcf"
        else _BASE_REQUIRED_FIELDS
    )


def _fact_mappings(required_fields: tuple[str, ...]) -> list[JSONObject]:
    return [
        {
            "decision_id": f"{_MAPPING_VERSION}-{field}",
            "mapping_version": _MAPPING_VERSION,
            "normalized_field": field,
        }
        for field in required_fields
    ]


def _validate_ingestion_result(
    result: object,
    *,
    identity: JSONObject,
    valuation_timestamp: datetime,
) -> JSONObject:
    payload = _mapping(result, context="Fundamental SEC ingestion result")
    status = payload.get("status")
    if status in {"degraded", "abstain"}:
        raise FundamentalServiceFailure(
            "SEC_INGESTION_DEGRADED",
            f"Fundamental SEC ingestion returned {status}",
            retryable=False,
            status_code=422,
        )
    if status not in {"created", "reused"}:
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental SEC ingestion returned an unknown status",
            retryable=False,
            status_code=502,
        )
    if payload.get("identity") != identity:
        raise FundamentalServiceFailure(
            "IDENTITY_MISMATCH",
            "Fundamental SEC ingestion changed the resolved identity",
            retryable=False,
            status_code=502,
        )
    response_timestamp = payload.get("valuation_timestamp")
    if not isinstance(response_timestamp, str):
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental SEC ingestion omitted valuation_timestamp",
            retryable=False,
            status_code=502,
        )
    if _timestamp(response_timestamp) != valuation_timestamp:
        raise FundamentalServiceFailure(
            "VALUATION_TIMESTAMP_MISMATCH",
            "Fundamental SEC ingestion changed valuation_timestamp",
            retryable=False,
            status_code=502,
        )
    snapshot_id = payload.get("snapshot_id")
    manifest_digest = payload.get("manifest_digest")
    fact_ids = payload.get("canonical_fact_ids")
    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id
        or not isinstance(manifest_digest, str)
        or not _DIGEST_PATTERN.fullmatch(manifest_digest)
        or not isinstance(fact_ids, list | tuple)
        or not fact_ids
        or any(not isinstance(fact_id, str) or not fact_id for fact_id in fact_ids)
        or len(set(fact_ids)) != len(fact_ids)
        or payload.get("quality_status") != "verified"
    ):
        raise FundamentalServiceFailure(
            "SEC_INGESTION_UNAVAILABLE",
            "Fundamental SEC ingestion did not return a verified snapshot",
            retryable=False,
            status_code=422,
        )
    return dict(payload)


async def prepare_service_valuation_request(
    state: Mapping[str, object],
    *,
    client: FundamentalServiceClient,
    principal: InternalPrincipal,
    correlation_id: str,
    deadline_at: datetime,
    request_timing: FundamentalRequestTimingV1 | None = None,
) -> PreparedServiceValuation:
    """Resolve identity and ingest the exact snapshot used by valuation.

    Caller assumptions remain caller-owned. A missing complete request therefore
    returns service evidence with an explicit reason instead of inventing values.
    """

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
    model_id = _model_id(request, fundamental)
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
    fiscal_period_selector = (
        request_timing.fiscal_period_selector.model_dump(mode="json")
        if request_timing is not None and request is not None
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
    cik = identity.get("issuer_id")
    if not isinstance(cik, str) or not cik.isdigit():
        raise FundamentalServiceFailure(
            "UPSTREAM_MALFORMED",
            "Fundamental identity resolver returned an invalid issuer id",
            retryable=False,
            status_code=502,
        )
    required_fields = _required_fields(model_id)
    snapshot_selector: JSONObject = {
        "contract_version": "fundamental.v1",
        "release_profile_id": _DATA_RELEASE_PROFILE_ID,
        "identity": identity,
        "valuation_timestamp": valuation_timestamp.isoformat().replace("+00:00", "Z"),
        **(
            {"fiscal_period_selector": fiscal_period_selector}
            if fiscal_period_selector is not None
            else {}
        ),
        "source_selection_policy": _SNAPSHOT_POLICY,
        "coverage_profile": _COVERAGE_PROFILE,
        "required_fields": list(required_fields),
    }
    compact_request = request is not None and is_compact_valuation_request(request)
    if request is None:
        # A report-only request reads the already activated immutable release.
        # Ingesting here would create a new snapshot outside that release and
        # make the subsequent release-bound resolution fail closed.
        return PreparedServiceValuation(
            valuation_request=None,
            identity=identity,
            ingestion={},
            snapshot_selector=snapshot_selector,
            reason="caller valuation assumptions are required",
        )
    ingestion = _validate_ingestion_result(
        (
            await client.execute(
                "ingest_sec_data",
                {
                    "contract_version": "fundamental.v1",
                    "identity": identity,
                    "cik": cik.zfill(10),
                    "ticker": ticker,
                    "valuation_timestamp": valuation_timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    **(
                        {"fiscal_period_selector": fiscal_period_selector}
                        if fiscal_period_selector is not None
                        else {}
                    ),
                    "required_fields": list(required_fields),
                    "mappings": _fact_mappings(required_fields),
                    "source_selection_policy": _INGESTION_POLICY,
                    "coverage_profile": _COVERAGE_PROFILE,
                    "legal_use_profile": _LEGAL_USE_PROFILE,
                    "filing": {"forms": ["10-K", "10-Q"], "lookback_days": 3650},
                    "parser_version": _PARSER_VERSION,
                    "validation_profile_id": _VALIDATION_PROFILE_ID,
                    "taxonomy_manifest_id": _TAXONOMY_MANIFEST_ID,
                    "taxonomy_version": _TAXONOMY_VERSION,
                    "policy_version": _POLICY_VERSION,
                },
                principal=principal,
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
        ).result,
        identity=identity,
        valuation_timestamp=valuation_timestamp,
    )
    prepared = (
        _normalize_compact_request(
            request,
            model_id=model_id,
            valuation_context=valuation_context,
            valuation_timestamp=valuation_timestamp,
            fiscal_period_selector=fiscal_period_selector,
        )
        if compact_request
        else dict(request)
    )
    prepared["contract_version"] = "fundamental.v1"
    prepared["identity"] = identity
    prepared["model_id"] = model_id
    prepared["model_version"] = (
        prepared.get("model_version") or _MODEL_VERSION[model_id]
    )
    prepared["historical_facts"] = list(ingestion["canonical_fact_ids"])
    prepared["snapshot_selector"] = snapshot_selector
    prepared["valuation_context"] = {
        **(
            _mapping(prepared.get("valuation_context"), context="valuation_context")
            if compact_request
            else valuation_context
        ),
        "valuation_timestamp": snapshot_selector["valuation_timestamp"],
        **(
            {"fiscal_period_selector": fiscal_period_selector}
            if fiscal_period_selector is not None
            else {}
        ),
        "source_selection_policy": _SNAPSHOT_POLICY,
        "coverage_profile": _COVERAGE_PROFILE,
    }
    return PreparedServiceValuation(
        valuation_request=prepared,
        identity=identity,
        ingestion=ingestion,
        snapshot_selector=snapshot_selector,
    )


__all__ = [
    "PreparedServiceValuation",
    "is_compact_valuation_request",
    "prepare_service_valuation_request",
]
