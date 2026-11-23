"""Bind resolver ticker-series keys to service-selected canonical identities."""

from collections.abc import Mapping
from typing import Literal

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.shared.artifacts.fundamental_contracts import FundamentalIdentityV1
from src.shared.kernel.types import JSONObject

SnapshotIdentitySelectionPolicy = Literal["exact-identity-v1", "sec-ticker-series-v1"]
_SERIES_FIELDS = ("issuer_id", "security_id", "currency", "domicile", "reporting_basis")


def snapshot_identity_selection_policy(
    resolved: FundamentalIdentityV1,
) -> SnapshotIdentitySelectionPolicy:
    return (
        "sec-ticker-series-v1"
        if resolved.share_class == resolved.security_id
        else "exact-identity-v1"
    )


def identity_matches_resolver(
    resolved: Mapping[str, object],
    canonical: Mapping[str, object],
    *,
    policy: str,
) -> bool:
    if policy == "exact-identity-v1":
        return dict(canonical) == dict(resolved)
    return (
        policy == "sec-ticker-series-v1"
        and resolved.get("share_class") == resolved.get("security_id")
        and all(canonical.get(field) == resolved.get(field) for field in _SERIES_FIELDS)
    )


def canonical_snapshot_identity(
    result: Mapping[str, object],
    *,
    resolved: Mapping[str, object],
    policy: str,
) -> JSONObject:
    try:
        canonical = FundamentalIdentityV1.model_validate(result.get("identity"))
    except ValueError as error:
        raise FundamentalServiceFailure(
            "SNAPSHOT_IDENTITY_MISMATCH",
            "Fundamental snapshot returned an invalid canonical identity",
            retryable=False,
            status_code=502,
        ) from error
    value = canonical.model_dump(mode="json")
    if result.get(
        "identity_selection_policy"
    ) != policy or not identity_matches_resolver(resolved, value, policy=policy):
        raise FundamentalServiceFailure(
            "SNAPSHOT_IDENTITY_MISMATCH",
            "Fundamental snapshot changed its identity policy or resolved series",
            retryable=False,
            status_code=502,
        )
    return value
