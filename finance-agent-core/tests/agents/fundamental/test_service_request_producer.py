from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalReleaseSelector,
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.services.service_request_producer import (
    prepare_service_valuation_request,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalActiveReleaseV1,
    FundamentalIdentityResolutionV1,
    FundamentalServiceResponseV1,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalRequestTimingV1,
)
from src.shared.artifacts.fundamental_contracts import (
    FundamentalValuationPreparationResultV1,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.internal_services import InternalPrincipal


class _Client:
    def __init__(self, *, snapshot: Mapping[str, object]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.snapshot = dict(snapshot)
        self.last_preparation: FundamentalValuationPreparationResultV1 | None = None

    async def resolve_identity(self, request, **_kwargs):
        self.calls.append(("resolve_identity", request.model_dump(mode="json")))
        identity = {
            "issuer_id": "0000320193",
            "issuer_name": "Apple Inc.",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "AAPL",
            "share_class": "AAPL",
            "currency": "USD",
        }
        payload = {
            "ticker": "AAPL",
            "identity": identity,
            "mapping_version": "sec-issuer-identity-v1",
            "source_evidence": tuple(
                {
                    "source_id": source_id,
                    "source_uri": f"https://sec.test/{source_id}",
                    "content_hash": "a" * 64,
                    "captured_at": "2026-11-07T00:00:00Z",
                    "available_at": "2026-11-07T00:00:00Z",
                    "media_type": "application/json",
                    "byte_count": 1,
                }
                for source_id in (
                    "sec-company-tickers",
                    "sec-submissions",
                    "sec-companyfacts",
                )
            ),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return FundamentalIdentityResolutionV1.model_validate_json(
            json.dumps(
                {**payload, "resolution_digest": hashlib.sha256(canonical).hexdigest()},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    async def read_active_release(self, profile_id, **_kwargs):
        self.calls.append(("read_active_release", {"profile_id": profile_id}))
        return FundamentalActiveReleaseV1.model_validate(_release(profile_id))

    async def execute(self, operation, input_payload, **_kwargs):
        self.calls.append((operation, dict(input_payload)))
        if operation == "resolve_snapshot":
            return FundamentalServiceResponseV1(
                contract_version="internal.v1",
                schema_version="fundamental.v1",
                correlation_id="correlation-1",
                result={
                    "contract_version": "fundamental.v1",
                    "snapshot_id": "snapshot-aapl-1",
                    "data_release_manifest_digest": self.snapshot["manifest_digest"],
                    "historical_facts": self.snapshot["canonical_fact_ids"],
                    "identity": input_payload["identity"],
                    "identity_selection_policy": input_payload.get(
                        "identity_selection_policy", "exact-identity-v1"
                    ),
                    "valuation_timestamp": input_payload["valuation_timestamp"],
                    "snapshot_timestamp": input_payload["valuation_timestamp"],
                    "source_selection_policy": input_payload["source_selection_policy"],
                    "coverage_profile": input_payload["coverage_profile"],
                    "quality": "verified",
                    "issue_codes": [],
                    "provenance": {
                        "snapshot_id": "snapshot-aapl-1",
                        "data_release_manifest_digest": self.snapshot[
                            "manifest_digest"
                        ],
                    },
                },
            )
        if operation == "override_prepared_valuation":
            if self.last_preparation is None:
                raise AssertionError("override called before preparation")
            return FundamentalServiceResponseV1(
                contract_version="internal.v1",
                schema_version="fundamental.v1",
                correlation_id="correlation-1",
                result=self.last_preparation.model_dump(mode="json"),
            )
        raise AssertionError(f"unexpected operation {operation}")

    async def prepare_valuation(self, input_payload, **_kwargs):
        prepared = {
            "contract_version": "fundamental.v1",
            "identity": {
                "issuer_id": "0000320193",
                "issuer_name": "Apple Inc.",
                "domicile": "US",
                "reporting_basis": "us-gaap",
                "security_id": "AAPL",
                "share_class": "AAPL",
                "currency": "USD",
            },
            "valuation_context": {
                "valuation_timestamp": "2026-11-07T00:00:00Z",
                "data_snapshot_id": input_payload["snapshot_id"],
                "data_release_manifest_digest": input_payload[
                    "data_release_manifest_digest"
                ],
                "source_selection_policy": "pit-v1",
                "coverage_profile": "fcff-valuation-requirements-v3",
            },
            "historical_facts": list(self.snapshot["canonical_fact_ids"]),
            "assumptions": {
                "forecast": {"base_revenue": "100"},
                "trace": {"description": "service-owned fixture assumptions"},
            },
            "uncertainty": {"mode": "none"},
            "quality": {"status": "provisional"},
            "provenance": {
                "snapshot_id": input_payload["snapshot_id"],
                "fact_ids": list(self.snapshot["canonical_fact_ids"]),
                "mapping_version": "sec-us-gaap-v1",
                "parser_version": "2.47.4",
                "taxonomy_version": "us-gaap-2023-2024",
                "policy_version": "sec-public-pit-v1",
            },
            "model_id": input_payload["model_id"],
            "model_version": f"{input_payload['model_id']}-v2",
            "policy_id": "fcff_dcf-us-gaap-public-v2",
            "input_digest": None,
        }
        self.calls.append(("prepare_valuation", dict(input_payload)))
        self.last_preparation = FundamentalValuationPreparationResultV1.model_validate(
            {
                "contract_version": "fundamental.v1",
                "status": "prepared",
                "model_id": input_payload["model_id"],
                "model_version": f"{input_payload['model_id']}-v2",
                "profile_id": "fcff-valuation-requirements-v3",
                "profile_digest": "d" * 64,
                "policy_id": "fcff_dcf-us-gaap-public-v2",
                "policy_version": "fcff_dcf-v2-quality-v1",
                "quality_status": "provisional",
                "issue_codes": ["HISTORY_THRESHOLD_UNVALIDATED"],
                "missing_evidence": [],
                "historical_metrics": {
                    "profile_id": "fcff-valuation-requirements-v3",
                    "profile_digest": "d" * 64,
                    "quality_status": "provisional",
                },
                "assumptions_evidence": [],
                "input": prepared,
                "preparation_digest": "e" * 64,
            }
        )
        return self.last_preparation


def _principal() -> InternalPrincipal:
    return InternalPrincipal(
        subject_id="subject-1", organization_id="org-1", membership_id="member-1"
    )


def _snapshot() -> dict[str, object]:
    return {
        "manifest_digest": "b" * 64,
        "canonical_fact_ids": ["fact-revenue", "fact-operating-income"],
    }


def _release(profile_id: str = "configured-release-v1") -> dict[str, object]:
    return {
        "active": {
            "profile_id": profile_id,
            "manifest_digest": "b" * 64,
            "revision": 1,
            "activated_at": "2026-11-07T00:00:00Z",
        },
        "manifest": {
            "profile_id": profile_id,
            "manifest_digest": "b" * 64,
            "required_fields": ["revenue", "operating_income"],
            "service_owned_compound_policy": {"retained_by_service": True},
        },
    }


_SELECTOR = FundamentalReleaseSelector(
    profile_id="configured-release-v1",
    coverage_profile="automatic-fcff-v1",
    source_selection_policy="pit-v1",
)


def _state(request: Mapping[str, object] | None = None) -> dict[str, object]:
    return {
        "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
        "fundamental_analysis": {"model_type": "dcf_standard"},
        **({"valuation_request": dict(request)} if request is not None else {}),
    }


async def _prepare(
    client: _Client, request: Mapping[str, object] | None = None, **kwargs
):
    return await prepare_service_valuation_request(
        _state(request),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        release_selector=_SELECTOR,
        request_timing=FundamentalRequestTimingV1.accept(
            request or {}, clock=lambda: datetime(2026, 11, 7, tzinfo=UTC)
        ),
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "valuation_request",
    [None, {"model_id": "fcff_dcf"}, {"model_id": "transition_fcff_dcf"}],
)
async def test_configured_release_owns_fields_and_reuses_snapshot_without_ingesting(
    valuation_request,
) -> None:
    client = _Client(snapshot=_snapshot())
    prepared = await _prepare(client, valuation_request)
    assert prepared.release_manifest_digest == "b" * 64
    assert prepared.snapshot_selector["release_profile_id"] == _SELECTOR.profile_id
    assert prepared.snapshot_selector["coverage_profile"] == "automatic-fcff-v1"
    assert prepared.snapshot_selector["source_selection_policy"] == "pit-v1"
    assert prepared.snapshot_selector["required_fields"] == [
        "revenue",
        "operating_income",
    ]
    assert "fiscal_period_selector" not in prepared.snapshot_selector
    operations = [name for name, _ in client.calls]
    assert operations == (
        ["resolve_identity", "read_active_release"]
        if valuation_request is None
        else [
            "resolve_identity",
            "read_active_release",
            "resolve_snapshot",
            "prepare_valuation",
        ]
    )
    if valuation_request is None:
        assert prepared.valuation_request is None
    else:
        assert prepared.valuation_request["model_id"] == valuation_request["model_id"]
        assert prepared.valuation_request["historical_facts"] == [
            "fact-revenue",
            "fact-operating-income",
        ]
        assert (
            prepared.valuation_request["provenance"]["mapping_version"]
            == "sec-us-gaap-v1"
        )


@pytest.mark.asyncio
async def test_missing_release_configuration_refuses_without_upstream_calls() -> None:
    client = _Client(snapshot=_snapshot())
    with pytest.raises(FundamentalServiceFailure) as error:
        await prepare_service_valuation_request(
            _state({"model_id": "fcff_dcf"}),
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )
    assert error.value.code == "SERVICE_NOT_CONFIGURED"
    assert client.calls == []


@pytest.mark.asyncio
async def test_refuses_a_different_configured_profile() -> None:
    class WrongProfile(_Client):
        async def read_active_release(self, profile_id, **kwargs):
            return FundamentalActiveReleaseV1.model_validate(
                _release("different-profile")
            )

    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(WrongProfile(snapshot=_snapshot()), {"model_id": "fcff_dcf"})
    assert error.value.code == "RELEASE_PROFILE_MISMATCH"


@pytest.mark.asyncio
async def test_release_refusal_propagates_without_ingestion_fallback() -> None:
    class Unavailable(_Client):
        async def read_active_release(self, profile_id, **kwargs):
            raise FundamentalServiceFailure(
                "DATA_RELEASE_NOT_ACTIVE",
                "not active",
                retryable=False,
                status_code=404,
            )

    client = Unavailable(snapshot=_snapshot())
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, {"model_id": "fcff_dcf"})
    assert error.value.code == "DATA_RELEASE_NOT_ACTIVE"
    assert [name for name, _ in client.calls] == ["resolve_identity"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["digest", "identity", "timestamp"])
async def test_selection_rejects_changed_release_identity_or_time_before_preparation(
    changed: str,
) -> None:
    class ChangedSelection(_Client):
        async def execute(self, operation, input_payload, **kwargs):
            response = await super().execute(operation, input_payload, **kwargs)
            result = dict(response.result)
            if changed == "digest":
                result["data_release_manifest_digest"] = "c" * 64
            elif changed == "identity":
                result["identity"] = {"security_id": "WRONG"}
            else:
                result["valuation_timestamp"] = "2026-11-08T00:00:00Z"
            return response.model_copy(update={"result": result})

    client = ChangedSelection(snapshot=_snapshot())
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, {"model_id": "fcff_dcf"})
    assert error.value.code == (
        "RELEASE_DIGEST_MISMATCH"
        if changed == "digest"
        else "SNAPSHOT_IDENTITY_MISMATCH"
        if changed == "identity"
        else "SNAPSHOT_PREPARATION_UNAVAILABLE"
    )
    assert "prepare_valuation" not in [name for name, _ in client.calls]


@pytest.mark.asyncio
async def test_explicit_period_selection_is_preserved() -> None:
    prepared = await _prepare(
        _Client(snapshot=_snapshot()),
        {
            "model_id": "fcff_dcf",
            "fiscal_period_selector": {"mode": "latest_complete", "count": 1},
        },
    )
    assert prepared.snapshot_selector["fiscal_period_selector"] == {
        "version": "fundamental.fiscal-period-selector.v1",
        "mode": "latest_complete",
        "count": 1,
    }


@pytest.mark.asyncio
async def test_browser_manual_override_is_rejected_before_service_calls() -> None:
    client = _Client(snapshot=_snapshot())
    override = {
        "contract_version": "fundamental.v1",
        "path": "assumptions.forecast.base_revenue",
        "value": "110",
        "provenance": {
            "author": "workspace-user",
            "modified_at": "2026-11-07T00:00:00Z",
            "reason": "Reviewed filing",
            "automatic_preparation_digest": "e" * 64,
        },
    }
    with pytest.raises(ValueError, match="manual_override"):
        await _prepare(client, {"model_id": "fcff_dcf", "manual_override": override})
    assert client.calls == []


class _CanonicalSnapshotClient(_Client):
    def __init__(self):
        super().__init__(snapshot=_snapshot())
        self.canonical = None
        self.tamper = None
        self.exact_identity = False

    async def resolve_identity(self, request, **kwargs):
        resolved = await super().resolve_identity(request, **kwargs)
        if self.exact_identity:
            return resolved.model_copy(
                update={
                    "identity": resolved.identity.model_copy(
                        update={"share_class": "common"}
                    )
                }
            )
        return resolved

    async def execute(self, operation, input_payload, **kwargs):
        if operation == "resolve_snapshot" and self.tamper == "ambiguous":
            raise FundamentalServiceFailure(
                "SNAPSHOT_IDENTITY_AMBIGUOUS",
                "Multiple canonical share classes",
                retryable=False,
                status_code=422,
            )
        response = await super().execute(operation, input_payload, **kwargs)
        if operation != "resolve_snapshot":
            return response
        payload = dict(response.result)
        self.canonical = {
            **payload["identity"],
            "issuer_name": "APPLE INC",
            "share_class": "CommonStock",
        }
        if self.tamper in {
            "issuer_id",
            "security_id",
            "currency",
            "domicile",
            "reporting_basis",
        }:
            replacement = {
                "currency": "EUR",
                "domicile": "GB",
                "reporting_basis": "ifrs",
            }.get(self.tamper, "different")
            self.canonical[self.tamper] = replacement
        payload["identity"] = self.canonical
        if self.tamper == "policy":
            payload["identity_selection_policy"] = "exact-identity-v1"
        if self.tamper == "missing_policy":
            payload.pop("identity_selection_policy")
        return response.model_copy(update={"result": payload})

    async def prepare_valuation(self, input_payload, **kwargs):
        preparation = await super().prepare_valuation(input_payload, **kwargs)
        return preparation.model_copy(
            update={"input": {**preparation.input, "identity": self.canonical}}
        )


async def test_typed_resolver_opts_into_series_and_adopts_canonical_snapshot_identity():
    client = _CanonicalSnapshotClient()
    prepared = await _prepare(client, {"model_id": "fcff_dcf"})
    selector = next(
        payload
        for operation, payload in client.calls
        if operation == "resolve_snapshot"
    )
    assert selector["identity_selection_policy"] == "sec-ticker-series-v1"
    assert (
        selector["identity"]["share_class"]
        == selector["identity"]["security_id"]
        == "AAPL"
    )
    assert prepared.identity == client.canonical
    assert prepared.valuation_request["identity"]["share_class"] == "CommonStock"


@pytest.mark.parametrize(
    "tamper",
    [
        "issuer_id",
        "security_id",
        "currency",
        "domicile",
        "reporting_basis",
        "policy",
        "missing_policy",
        "ambiguous",
    ],
)
async def test_canonical_snapshot_identity_rejects_changed_series_or_policy(tamper):
    client = _CanonicalSnapshotClient()
    client.tamper = tamper
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, {"model_id": "fcff_dcf"})
    assert error.value.code == (
        "SNAPSHOT_IDENTITY_AMBIGUOUS"
        if tamper == "ambiguous"
        else "SNAPSHOT_IDENTITY_MISMATCH"
    )
    assert "prepare_valuation" not in [operation for operation, _ in client.calls]


async def test_non_series_resolver_preserves_exact_identity_selection():
    client = _CanonicalSnapshotClient()
    client.exact_identity = True
    with pytest.raises(FundamentalServiceFailure) as error:
        await _prepare(client, {"model_id": "fcff_dcf"})
    assert error.value.code == "SNAPSHOT_IDENTITY_MISMATCH"
    selector = next(
        payload
        for operation, payload in client.calls
        if operation == "resolve_snapshot"
    )
    assert selector["identity_selection_policy"] == "exact-identity-v1"
