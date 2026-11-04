from __future__ import annotations

from collections.abc import Mapping

import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.service_valuation_flow import (  # noqa: E501
    read_service_valuation_input,
    run_service_valuation_flow,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalServiceResponseV1,
)
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)


class _Runtime:
    def build_valuation_error_update(self, error: str) -> dict[str, object]:
        return {"error": error}


class _Client:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        result_digest: str = "a" * 64,
        validated_input: Mapping[str, object] | None = None,
        resolved_snapshot: Mapping[str, object] | None = None,
    ):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failure = failure
        self.result_digest = result_digest
        self.validated_input = validated_input
        self.resolved_snapshot = resolved_snapshot

    async def execute(
        self,
        operation: str,
        input_payload: Mapping[str, object],
        **_: object,
    ) -> FundamentalServiceResponseV1:
        self.calls.append((operation, dict(input_payload)))
        if self.failure is not None:
            raise self.failure
        if operation == "resolve_snapshot":
            return FundamentalServiceResponseV1(
                correlation_id="trace-281",
                contract_version="internal.v1",
                schema_version="fundamental.v1",
                result=dict(
                    self.resolved_snapshot
                    or {
                        "snapshot_id": "snapshot-resolved",
                        "historical_facts": ["fact-revenue"],
                        "identity": input_payload["identity"],
                        "valuation_timestamp": input_payload["valuation_timestamp"],
                        "source_selection_policy": "pit-v1",
                        "coverage_profile": "us-gaap-public-v1",
                        "quality": "verified",
                        "issue_codes": [],
                        "provenance": {
                            "snapshot_id": "snapshot-resolved",
                            "mapping_version": "mapping-v1",
                            "parser_version": "parser-v1",
                            "taxonomy_version": "taxonomy-v1",
                        },
                    }
                ),
            )
        if operation == "validate":
            return FundamentalServiceResponseV1(
                correlation_id="trace-281",
                contract_version="internal.v1",
                schema_version="fundamental.v1",
                result={
                    "contract_version": "fundamental.v1",
                    "input": dict(self.validated_input or input_payload),
                    "input_digest": "a" * 64,
                    "quality_status": "verified",
                    "issue_codes": ["QUALITY_OK"],
                    "missing_evidence": [],
                },
            )
        primary = {
            "contract_version": "fundamental.v1",
            "calculation_version": "calculator-v1",
            "calculation_status": "completed",
            "quality_status": "verified",
            "input_digest": self.result_digest,
            "result_hash": "b" * 64,
            "intrinsic_value": "123.45",
            "per_share_value": "1.23",
            "assumptions": input_payload["assumptions"],
            "model_version": input_payload["model_version"],
            "policy_version": "policy-v1",
            "issue_codes": [],
            "missing_evidence": [],
            "snapshot_id": "snapshot-1",
            "evaluated_at": "2026-11-04T00:00:00Z",
            "correlation_id": "trace-281",
        }
        result: dict[str, object] = primary
        if operation == "uncertainty":
            monte_carlo = input_payload["monte_carlo"]["uncertainty"]
            result = {
                "status": "verified",
                "base": {**primary, "input_digest": "c" * 64},
                "requested_samples": monte_carlo["samples"],
                "valid_samples": monte_carlo["samples"],
                "invalid_samples": 0,
                "invalid_draw_policy": monte_carlo["invalid_draw_policy"],
                "seed": monte_carlo["seed"],
                "sampler_version": "python-random-v1",
                "quantiles": {"p05": "1.0", "p50": "1.2", "p95": "1.4"},
                "convergence_diagnostics": {"converged": True},
            }
        return FundamentalServiceResponseV1(
            correlation_id="trace-281",
            contract_version="internal.v1",
            schema_version="fundamental.v1",
            result=result,
        )


def _input(*, monte_carlo: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "fundamental.v1",
        "identity": {
            "issuer_id": "CIK1",
            "issuer_name": "Example Corp",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "COMMON",
            "share_class": "common",
            "currency": "USD",
        },
        "valuation_context": {
            "valuation_timestamp": "2026-11-04T00:00:00Z",
            "data_snapshot_id": "snapshot-1",
            "source_selection_policy": "pit-v1",
            "coverage_profile": "us-gaap-public-v1",
        },
        "historical_facts": ["revenue"],
        "assumptions": {
            "forecast": {
                "base_revenue": "100",
                "revenue_growth": ["0.05"],
                "operating_margin": ["0.15"],
                "reinvestment_rate": ["0.20"],
            },
            "wacc": {
                "risk_free_rate": "0.04",
                "beta": "1.1",
                "equity_risk_premium": "0.05",
                "pre_tax_cost_of_debt": "0.05",
                "tax_rate": "0.21",
                "debt_weight": "0.2",
                "equity_weight": "0.8",
            },
            "terminal_growth": "0.02",
            "capital_bridge": {
                "cash": "10",
                "debt": "5",
                "preferred_stock": "0",
                "lease_liabilities": "0",
                "non_controlling_interest": "0",
                "diluted_shares": "100",
            },
            "trace": {"description": "fixture assumptions"},
        },
        "uncertainty": {
            "mode": "monte_carlo" if monte_carlo else "none",
        },
        "quality": {"status": "verified"},
        "provenance": {
            "snapshot_id": "snapshot-1",
            "mapping_version": "mapping-v1",
            "parser_version": "parser-v1",
            "taxonomy_version": "taxonomy-v1",
        },
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v1",
        "input_digest": None,
    }
    if monte_carlo:
        payload["uncertainty"] = {
            "mode": "monte_carlo",
            "samples": 10,
            "seed": 7,
            "invalid_draw_policy": "skip",
            "parameters": [
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": "0.01",
                    "upper": "0.03",
                }
            ],
        }
    return payload


@pytest.mark.asyncio
async def test_cutover_resolves_snapshot_and_facts_through_service_boundary() -> None:
    client = _Client()
    payload = _input()
    payload.pop("historical_facts")
    payload["snapshot_selector"] = {
        "contract_version": "fundamental.v1",
        "identity": payload["identity"],
        "valuation_timestamp": payload["valuation_context"]["valuation_timestamp"],
        "source_selection_policy": "pit-v1",
        "coverage_profile": "us-gaap-public-v1",
        "required_fields": ["revenue"],
    }
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"fundamental_analysis": {"valuation_request": payload}},
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == [
        "resolve_snapshot",
        "validate",
        "calculate",
    ]
    assert client.calls[1][1]["historical_facts"] == ["fact-revenue"]
    assert client.calls[1][1]["valuation_context"]["data_snapshot_id"] == (
        "snapshot-resolved"
    )
    assert result.update["fundamental_analysis"]["input_digest"] == "a" * 64


@pytest.mark.asyncio
async def test_cutover_preserves_input_and_binds_caller_approval() -> None:
    client = _Client()
    state = {"fundamental_analysis": {"valuation_request": _input()}}
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1",
            organization_id="org-1",
            membership_id="membership-1",
        )
    )
    approvals: list[dict[str, object]] = []
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            state,
            client=client,
            request_approval_fn=lambda request: approvals.append(request)
            or {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == ["validate", "calculate"]
    assert (
        client.calls[0][1]["assumptions"]
        == state["fundamental_analysis"]["valuation_request"]["assumptions"]
    )
    assert (
        client.calls[1][1]["uncertainty"]
        == state["fundamental_analysis"]["valuation_request"]["uncertainty"]
    )
    assert client.calls[1][1]["caller_approval"] == {
        "input_digest": "a" * 64,
        "decision": "approved",
        "caller_id": "caller-1",
        "decided_at": client.calls[1][1]["caller_approval"]["decided_at"],
    }
    assert approvals[0]["parameters"]["input_digest"] == "a" * 64
    assert result.update["fundamental_analysis"]["result_hash"] == "b" * 64
    assert (
        result.update["fundamental_analysis"]["valuation_request"]
        == state["fundamental_analysis"]["valuation_request"]
    )


@pytest.mark.asyncio
async def test_cutover_routes_explicit_monte_carlo_controls_to_uncertainty() -> None:
    client = _Client()
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1",
            organization_id="org-1",
            membership_id="membership-1",
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"fundamental_analysis": {"valuation_request": _input(monte_carlo=True)}},
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == [
        "validate",
        "calculate",
        "uncertainty",
    ]
    assert client.calls[1][1]["caller_approval"]["input_digest"] == "a" * 64
    assert client.calls[2][1]["caller_approval"]["input_digest"] == "a" * 64
    assert (
        client.calls[2][1]["monte_carlo"]["uncertainty"]
        == _input(monte_carlo=True)["uncertainty"]
    )
    assert client.calls[2][1]["monte_carlo"]["uncertainty"]["samples"] == 10
    assert result.update["fundamental_analysis"]["quality_status"] == "verified"
    summary = result.update["fundamental_analysis"]["fundamental_service"][
        "uncertainty_summary"
    ]
    assert summary["seed"] == 7
    assert summary["requested_samples"] == 10
    assert summary["base"]["input_digest"] == "c" * 64


@pytest.mark.asyncio
async def test_cutover_rejects_service_assumption_rewrite() -> None:
    client = _Client(
        validated_input={**_input(), "assumptions": {"terminal_growth": "0.99"}}
    )
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"fundamental_analysis": {"valuation_request": _input()}},
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == ["validate"]
    assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
        "INPUT_ASSUMPTIONS_CHANGED"
    )


@pytest.mark.asyncio
async def test_cutover_rejects_calculation_digest_mismatch() -> None:
    client = _Client(result_digest="c" * 64)
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"fundamental_analysis": {"valuation_request": _input()}},
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == ["validate", "calculate"]
    assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
        "INPUT_DIGEST_MISMATCH"
    )


@pytest.mark.asyncio
async def test_service_failure_is_degraded_without_a_local_calculation() -> None:
    client = _Client(
        failure=FundamentalServiceFailure(
            "source_unavailable", "service unavailable", retryable=True
        )
    )
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"fundamental_analysis": {"valuation_request": _input()}},
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == ["validate"]
    assert result.update["fundamental_analysis"]["quality_status"] == "degraded"
    assert (
        result.update["fundamental_analysis"]["service_failure"]["code"]
        == "source_unavailable"
    )


def test_service_input_rejects_raw_legacy_reports() -> None:
    with pytest.raises(ValueError, match="legacy or raw"):
        read_service_valuation_input(
            {
                "fundamental_analysis": {
                    "valuation_request": {**_input(), "financial_reports": []}
                }
            }
        )


def test_service_input_accepts_root_caller_request() -> None:
    request = _input()
    assert read_service_valuation_input({"valuation_request": request}) == request


def test_service_input_rejects_extensions_outside_the_frozen_contract() -> None:
    with pytest.raises(ValueError, match="outside the frozen ValuationInputV1"):
        read_service_valuation_input(
            {"valuation_request": {**_input(monte_carlo=True), "monte_carlo": {}}}
        )
