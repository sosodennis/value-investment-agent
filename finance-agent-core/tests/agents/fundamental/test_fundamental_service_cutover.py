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
    FundamentalFactsReadResultV1,
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
        uncertainty_report_digest: str | None = None,
        uncertainty_base_digest: str = "b" * 64,
        uncertainty_base_overrides: Mapping[str, object] | None = None,
        uncertainty_trace_overrides: Mapping[str, object] | None = None,
        uncertainty_report_references: list[Mapping[str, object]] | None = None,
        calculation_overrides: Mapping[str, object] | None = None,
        calculation_trace_overrides: Mapping[str, object] | None = None,
        facts_snapshot_id: str | None = None,
        facts_manifest_digest: str = "e" * 64,
        facts_ids: list[str] | None = None,
        validation_policy_overrides: Mapping[str, object] | None = None,
        validated_input: Mapping[str, object] | None = None,
        resolved_snapshot: Mapping[str, object] | None = None,
        snapshot_policy_version: str = "pit-v1",
    ):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failure = failure
        self.result_digest = result_digest
        self.uncertainty_report_digest = uncertainty_report_digest or result_digest
        self.uncertainty_base_digest = uncertainty_base_digest
        self.uncertainty_base_overrides = dict(uncertainty_base_overrides or {})
        self.uncertainty_trace_overrides = dict(uncertainty_trace_overrides or {})
        self.uncertainty_report_references = uncertainty_report_references
        self.calculation_overrides = dict(calculation_overrides or {})
        self.calculation_trace_overrides = dict(calculation_trace_overrides or {})
        self.facts_snapshot_id = facts_snapshot_id
        self.facts_manifest_digest = facts_manifest_digest
        self.facts_ids = facts_ids
        self.validation_policy_overrides = dict(validation_policy_overrides or {})
        self.validated_input = validated_input
        self.resolved_snapshot = resolved_snapshot
        self.snapshot_policy_version = snapshot_policy_version
        self.facts_calls: list[dict[str, object]] = []

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
                            "policy_version": self.snapshot_policy_version,
                        },
                    }
                ),
            )
        if operation == "validate":
            validated_input = dict(self.validated_input or input_payload)
            validated_input["input_digest"] = "a" * 64
            provenance = validated_input["provenance"]
            policy_resolution = {
                "contract_version": "fundamental.v1",
                "policy_id": validated_input["policy_id"],
                "policy_version": provenance["policy_version"],
                "policy_digest": "1" * 64,
                "resolved_fields": {},
                "precedence": {},
                "input_digest": "a" * 64,
            }
            policy_resolution.update(self.validation_policy_overrides)
            return FundamentalServiceResponseV1(
                correlation_id="trace-281",
                contract_version="internal.v1",
                schema_version="fundamental.v1",
                result={
                    "contract_version": "fundamental.v1",
                    "input": validated_input,
                    "input_digest": "a" * 64,
                    "quality_status": "verified",
                    "policy_resolution": policy_resolution,
                    "issue_codes": ["QUALITY_OK"],
                    "missing_evidence": [],
                },
            )
        valuation_context = input_payload["valuation_context"]
        provenance = input_payload["provenance"]
        uncertainty = input_payload["uncertainty"]
        has_monte_carlo = (
            operation == "calculate"
            and isinstance(uncertainty, Mapping)
            and uncertainty.get("mode") == "monte_carlo"
        )
        calculation_digest = (
            self.uncertainty_base_digest if has_monte_carlo else self.result_digest
        )
        primary = {
            "contract_version": "fundamental.v1",
            "calculation_version": "calculator-v1",
            "calculation_status": "completed",
            "quality_status": "verified",
            "input_digest": calculation_digest,
            "result_hash": "b" * 64,
            "intrinsic_value": "123.45",
            "per_share_value": "1.23",
            "assumptions": input_payload["assumptions"],
            "model_version": input_payload["model_version"],
            "policy_version": provenance["policy_version"],
            "policy_id": input_payload["policy_id"],
            "policy_resolution": {
                "contract_version": "fundamental.v1",
                "policy_id": input_payload["policy_id"],
                "policy_version": provenance["policy_version"],
                "policy_digest": "1" * 64,
                "resolved_fields": {},
                "precedence": {},
                "input_digest": calculation_digest,
            },
            "artifact_references": [
                {
                    "artifact_id": "calculation-evidence-1",
                    "artifact_type": "calculation_evidence",
                    "content_hash": "d" * 64,
                }
            ],
            "trace": {
                "source_selection_policy": valuation_context["source_selection_policy"],
                "source_selection_policy_version": "pit-v1",
                "snapshot_id": valuation_context["data_snapshot_id"],
                "snapshot_manifest_digest": "e" * 64,
                "fact_ids": list(input_payload["historical_facts"]),
                "source_content_hashes": ["f" * 64],
                "policy_id": input_payload["policy_id"],
                "policy_version": provenance["policy_version"],
                "policy_digest": "1" * 64,
                "model_id": input_payload["model_id"],
                "model_version": input_payload["model_version"],
                "assumptions_digest": "2" * 64,
                "calculation_version": "calculator-v1",
            },
            "issue_codes": [],
            "missing_evidence": [],
            "snapshot_id": valuation_context["data_snapshot_id"],
            "evaluated_at": "2026-11-04T00:00:00Z",
            "correlation_id": "trace-281",
        }
        primary["trace"].update(self.calculation_trace_overrides)
        primary.update(self.calculation_overrides)
        result: dict[str, object] = primary
        if has_monte_carlo:
            assert isinstance(uncertainty, Mapping)
            monte_carlo = uncertainty
            uncertainty_reference = {
                "artifact_id": "uncertainty-evidence-1",
                "artifact_type": "uncertainty_evidence",
                "content_hash": "c" * 64,
            }
            base = {
                **primary,
                "input_digest": self.uncertainty_base_digest,
                **self.uncertainty_base_overrides,
            }
            base_trace = dict(base["trace"])
            base_trace.update(self.uncertainty_trace_overrides)
            base["trace"] = base_trace
            base["artifact_references"] = [
                *primary["artifact_references"],
                uncertainty_reference,
            ]
            result = {
                "status": "verified",
                "input_digest": self.uncertainty_report_digest,
                "base": base,
                "requested_samples": monte_carlo["samples"],
                "valid_samples": monte_carlo["samples"],
                "invalid_samples": 0,
                "invalid_draw_policy": monte_carlo["invalid_draw_policy"],
                "seed": monte_carlo["seed"],
                "sampler_version": "python-random-v1",
                "artifact_references": (
                    self.uncertainty_report_references
                    if self.uncertainty_report_references is not None
                    else [uncertainty_reference]
                ),
                "quantiles": {"p05": "1.0", "p50": "1.2", "p95": "1.4"},
                "convergence_diagnostics": {"converged": True},
            }
        return FundamentalServiceResponseV1(
            correlation_id="trace-281",
            contract_version="internal.v1",
            schema_version="fundamental.v1",
            result=result,
        )

    async def read_facts(
        self,
        input_payload: Mapping[str, object],
        **_: object,
    ) -> FundamentalFactsReadResultV1:
        self.facts_calls.append(dict(input_payload))
        if self.failure is not None:
            raise self.failure
        fact_ids = self.facts_ids or list(input_payload.get("required_fields", ()))
        snapshot_id = self.facts_snapshot_id or str(input_payload["snapshot_id"])
        facts = [
            {
                "contract_version": "fundamental.v1",
                "fact_id": fact_id,
                "issuer_id": "320193",
                "concept": f"us-gaap:{fact_id}",
                "normalized_field": fact_id,
                "value": 100,
                "unit": "USD",
                "scale": 0,
                "currency": "USD",
                "period_end": "2025-09-27",
                "context": {
                    "concept_qname": f"us-gaap:{fact_id}",
                    "period_type": "instant",
                    "instant": "2025-09-27",
                    "unit_qname": "iso4217:USD",
                    "measure": "iso4217:USD",
                    "entity_scope": "320193",
                    "consolidation_scope": "consolidated",
                    "context_id": f"I-{fact_id}",
                },
                "as_of": "2025-09-27T00:00:00Z",
                "available_at": "2025-11-01T00:00:00Z",
                "captured_at": "2025-11-02T00:00:00Z",
                "taxonomy_version": "taxonomy-v1",
                "source": {
                    "source_url": "https://www.sec.gov/Archives/filing.xml",
                    "content_hash": "f" * 64,
                    "source_role": "filing",
                    "captured_at": "2025-11-02T00:00:00Z",
                    "available_at": "2025-11-01T00:00:00Z",
                    "parser_version": "parser-v1",
                },
                "quality": "verified",
            }
            for fact_id in fact_ids
        ]
        return FundamentalFactsReadResultV1.model_validate(
            {
                "contract_version": "fundamental.v1",
                "snapshot_id": snapshot_id,
                "snapshot_manifest_digest": self.facts_manifest_digest,
                "identity": {
                    "issuer_id": "320193",
                    "issuer_name": "Apple Inc.",
                    "domicile": "US",
                    "reporting_basis": "us-gaap",
                    "security_id": "US0378331005",
                    "share_class": "common",
                    "currency": "USD",
                },
                "valuation_timestamp": "2026-01-15T00:00:00Z",
                "quality_status": "verified",
                "facts": facts,
            }
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
            "policy_version": "policy-v1",
        },
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v1",
        "policy_id": "fcff-dcf-policy-v1",
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
    client = _Client(facts_ids=["fact-revenue"])
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
    assert client.calls[1][1]["provenance"]["policy_version"] == "policy-v1"
    assert client.facts_calls == [
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": "snapshot-resolved",
            "data_release_manifest_digest": None,
            "required_fields": ["revenue"],
        }
    ]
    assert (
        result.update["fundamental_analysis"]["fundamental_service"]["facts"][
            "snapshot_id"
        ]
        == "snapshot-resolved"
    )
    assert (
        result.update["fundamental_analysis"]["fundamental_service"]["facts"][
            "snapshot_manifest_digest"
        ]
        == "e" * 64
    )
    assert result.update["fundamental_analysis"]["fundamental_service"]["facts"][
        "fact_ids"
    ] == ["fact-revenue"]
    assert result.update["fundamental_analysis"]["input_digest"] == "a" * 64


@pytest.mark.parametrize(
    ("client", "expected_operations"),
    (
        (
            _Client(validation_policy_overrides={"policy_digest": "invalid"}),
            ["validate"],
        ),
        (
            _Client(calculation_trace_overrides={"policy_digest": "9" * 64}),
            ["validate", "calculate"],
        ),
    ),
)
@pytest.mark.asyncio
async def test_cutover_rejects_unbound_policy_evidence(
    client: _Client, expected_operations: list[str]
) -> None:
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
            {"valuation_request": _input()},
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == expected_operations
    assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
        "UPSTREAM_MALFORMED"
    )


@pytest.mark.asyncio
async def test_cutover_binds_resolved_source_policy_version_to_calculation_trace() -> (
    None
):
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
    client = _Client(snapshot_policy_version="pit-v2")
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
            {"valuation_request": payload},
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
    assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
        "UPSTREAM_MALFORMED"
    )


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
async def test_cutover_accepts_canonical_defaults_without_changing_caller_values() -> (
    None
):
    payload = _input(monte_carlo=True)
    assumptions = {
        **payload["assumptions"],
        "trace": {
            **payload["assumptions"]["trace"],
            "expression": None,
            "inputs": [],
            "source_refs": [],
        },
    }
    uncertainty = {
        **payload["uncertainty"],
        "correlations": [],
        "scenarios": [],
        "sensitivity": [],
    }
    client = _Client(
        validated_input={
            **payload,
            "assumptions": assumptions,
            "uncertainty": uncertainty,
        }
    )
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

    assert [operation for operation, _ in client.calls] == ["validate", "calculate"]
    assert result.update["fundamental_analysis"]["quality_status"] == "verified"
    assert result.update["fundamental_analysis"]["valuation_request"] == payload


@pytest.mark.asyncio
async def test_cutover_routes_explicit_monte_carlo_controls_to_calculation_report() -> (
    None
):
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

    assert [operation for operation, _ in client.calls] == ["validate", "calculate"]
    assert client.calls[1][1]["caller_approval"]["input_digest"] == "a" * 64
    assert client.calls[1][1]["uncertainty"] == _input(monte_carlo=True)["uncertainty"]
    assert client.calls[1][1]["uncertainty"]["samples"] == 10
    assert result.update["fundamental_analysis"]["quality_status"] == "verified"
    projection = result.update["fundamental_analysis"]["fundamental_service"]
    assert projection["input_digest"] == "a" * 64
    assert projection["service_result"]["input_digest"] == "a" * 64
    summary = result.update["fundamental_analysis"]["fundamental_service"][
        "uncertainty_summary"
    ]
    assert summary["seed"] == 7
    assert summary["requested_samples"] == 10
    assert summary["base"]["input_digest"] == "b" * 64


@pytest.mark.asyncio
async def test_cutover_rejects_uncertainty_report_for_different_caller_input() -> None:
    client = _Client(uncertainty_report_digest="c" * 64)
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
            {"valuation_request": _input(monte_carlo=True)},
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
async def test_cutover_rejects_uncertainty_evidence_reference_mismatch() -> None:
    client = _Client(
        uncertainty_report_references=[
            {
                "artifact_id": "different-uncertainty-evidence",
                "artifact_type": "uncertainty_evidence",
                "content_hash": "9" * 64,
            }
        ]
    )
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
            {"valuation_request": _input(monte_carlo=True)},
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
        "UPSTREAM_MALFORMED"
    )


@pytest.mark.asyncio
async def test_cutover_rejects_unapproved_assumption_defaults() -> None:
    payload = _input()
    client = _Client(
        validated_input={
            **payload,
            "assumptions": {
                **payload["assumptions"],
                "terminal_growth_source": "service-default",
            },
        }
    )
    token = set_request_principal(
        InternalPrincipal(subject_id="caller-1", organization_id="org-1")
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"valuation_request": payload},
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
async def test_cutover_accepts_service_defined_optional_assumption_defaults() -> None:
    payload = _input()
    canonical_assumptions = {**payload["assumptions"], "bank": None}
    client = _Client(validated_input={**payload, "assumptions": canonical_assumptions})
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

    assert [operation for operation, _ in client.calls] == ["validate", "calculate"]
    assert result.update["fundamental_analysis"]["quality_status"] == "verified"
    assert client.calls[1][1]["assumptions"]["bank"] is None


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
async def test_cutover_rejects_service_uncertainty_rewrite() -> None:
    payload = _input(monte_carlo=True)
    client = _Client(
        validated_input={
            **payload,
            "uncertainty": {**payload["uncertainty"], "seed": 99},
        }
    )
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

    assert [operation for operation, _ in client.calls] == ["validate"]
    assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
        "INPUT_UNCERTAINTY_CHANGED"
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
async def test_cutover_rejects_uncertainty_base_digest_mismatch() -> None:
    client = _Client(uncertainty_base_overrides={"input_digest": "c" * 64})
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"valuation_request": _input(monte_carlo=True)},
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
        "UPSTREAM_MALFORMED"
    )


@pytest.mark.asyncio
async def test_cutover_rejects_uncertainty_base_artifact_mismatch() -> None:
    client = _Client(uncertainty_base_overrides={"result_hash": "invalid"})
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            _Runtime(),
            {"valuation_request": _input(monte_carlo=True)},
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
        "UPSTREAM_MALFORMED"
    )


@pytest.mark.asyncio
async def test_cutover_rejects_uncertainty_base_policy_trace_mismatch() -> None:
    client = _Client(uncertainty_trace_overrides={"policy_digest": "9" * 64})
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
            {"valuation_request": _input(monte_carlo=True)},
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
        "UPSTREAM_MALFORMED"
    )


@pytest.mark.asyncio
async def test_cutover_rejects_wrong_model_version_or_missing_artifact_reference() -> (
    None
):
    for overrides in (
        {"model_version": "fcff_dcf-unrequested-v99"},
        {"artifact_references": []},
        {"assumptions": {"terminal_growth": "0.99"}},
    ):
        client = _Client(calculation_overrides=overrides)
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
                {"valuation_request": _input()},
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
        ]
        assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
            "UPSTREAM_MALFORMED"
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
