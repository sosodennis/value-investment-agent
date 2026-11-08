from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.orchestrator import (
    FundamentalOrchestrator,
)
from src.agents.fundamental.application.workflow_orchestrator.service_valuation_flow import (  # noqa: E501
    read_service_valuation_input,
    run_service_valuation_flow,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalFactsReadResultV1,
    FundamentalIdentityResolutionV1,
    FundamentalServiceResponseV1,
)
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)


class _Runtime:
    def __init__(self) -> None:
        self.saved_calls: list[dict[str, object]] = []

    def build_valuation_error_update(self, error: str) -> dict[str, object]:
        return {"error": error}

    async def save_financial_reports(
        self,
        *,
        data: dict[str, object],
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        self.saved_calls.append(
            {"data": data, "produced_by": produced_by, "key_prefix": key_prefix}
        )
        return "service-valuation-artifact"


class _ArtifactStorage:
    def __init__(self) -> None:
        self.saved_calls: list[dict[str, object]] = []

    async def save_artifact(
        self,
        *,
        data: dict[str, object],
        artifact_type: str,
        produced_by: str,
        key_prefix: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        self.saved_calls.append(
            {
                "data": data,
                "artifact_type": artifact_type,
                "produced_by": produced_by,
                "key_prefix": key_prefix,
                "thread_id": thread_id,
            }
        )
        return "production-service-facts-artifact"


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
        facts_identity: Mapping[str, object] | None = None,
        facts_valuation_timestamp: str = "2026-01-15T00:00:00Z",
        validation_policy_overrides: Mapping[str, object] | None = None,
        validated_input: Mapping[str, object] | None = None,
        resolved_snapshot: Mapping[str, object] | None = None,
        snapshot_policy_version: str = "pit-v1",
    ):
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.deadlines: list[datetime] = []
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
        self.facts_identity = dict(
            facts_identity
            or {
                "issuer_id": "320193",
                "issuer_name": "Apple Inc.",
                "domicile": "US",
                "reporting_basis": "us-gaap",
                "security_id": "US0378331005",
                "share_class": "common",
                "currency": "USD",
            }
        )
        self.facts_valuation_timestamp = facts_valuation_timestamp
        self.validation_policy_overrides = dict(validation_policy_overrides or {})
        self.validated_input = validated_input
        self.resolved_snapshot = resolved_snapshot
        self.snapshot_policy_version = snapshot_policy_version
        self.facts_calls: list[dict[str, object]] = []

    async def execute(
        self,
        operation: str,
        input_payload: Mapping[str, object],
        **kwargs: object,
    ) -> FundamentalServiceResponseV1:
        self.calls.append((operation, dict(input_payload)))
        deadline_at = kwargs.get("deadline_at")
        if isinstance(deadline_at, datetime):
            self.deadlines.append(deadline_at)
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
                        "snapshot_timestamp": input_payload["valuation_timestamp"],
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
        if operation in {"validate", "validate_with_policy"}:
            validated_input = dict(self.validated_input or input_payload)
            if operation == "validate_with_policy":
                supplied_assumptions = validated_input["assumptions"]
                if isinstance(supplied_assumptions, Mapping):
                    validated_input["assumptions"] = {
                        **_input()["assumptions"],
                        **supplied_assumptions,
                    }
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
                "issuer_id": str(self.facts_identity["issuer_id"]),
                "security_id": self.facts_identity.get("security_id"),
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
                "identity": dict(self.facts_identity),
                "valuation_timestamp": self.facts_valuation_timestamp,
                "quality_status": "verified",
                "data_release_manifest_digest": None,
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


def _resolved_identity() -> FundamentalIdentityResolutionV1:
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
        "source_evidence": [
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
        ],
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


class _FactsOnlyClient(_Client):
    _fact_ids = [
        "fact-revenue",
        "fact-operating-income",
        "fact-cash",
        "fact-debt",
        "fact-diluted-shares",
    ]

    def __init__(
        self,
        *,
        facts_snapshot_id: str | None = None,
        facts_ids: list[str] | None = None,
        resolved_fact_ids: list[str] | None = None,
        snapshot_timestamp: str = "2026-11-01T00:00:00Z",
    ) -> None:
        identity = _resolved_identity().identity.model_dump(mode="json")
        self.resolved_fact_ids = list(resolved_fact_ids or self._fact_ids)
        super().__init__(
            facts_snapshot_id=facts_snapshot_id,
            facts_ids=facts_ids if facts_ids is not None else self.resolved_fact_ids,
            facts_identity=identity,
            facts_valuation_timestamp=snapshot_timestamp,
        )
        self.identity = identity
        self.snapshot_timestamp = snapshot_timestamp

    async def resolve_identity(self, request, **_kwargs):
        self.calls.append(("resolve_identity", request.model_dump(mode="json")))
        return _resolved_identity()

    async def execute(self, operation, input_payload, **kwargs):
        if operation == "ingest_sec_data":
            self.calls.append((operation, dict(input_payload)))
            self.facts_valuation_timestamp = str(input_payload["valuation_timestamp"])
            result = {
                "contract_version": "fundamental.v1",
                "status": "created",
                "identity": dict(input_payload["identity"]),
                "valuation_timestamp": input_payload["valuation_timestamp"],
                "snapshot_id": "snapshot-aapl-ingested",
                "manifest_digest": "b" * 64,
                "canonical_fact_ids": list(self._fact_ids),
                "quality_status": "verified",
            }
            return FundamentalServiceResponseV1(
                correlation_id="trace-facts-only",
                contract_version="internal.v1",
                schema_version="fundamental.v1",
                result=result,
            )
        if operation == "resolve_snapshot":
            self.facts_valuation_timestamp = self.snapshot_timestamp
            self.resolved_snapshot = {
                "contract_version": "fundamental.v1",
                "snapshot_id": "snapshot-aapl-resolved",
                "historical_facts": self.resolved_fact_ids,
                "identity": self.identity,
                "valuation_timestamp": input_payload["valuation_timestamp"],
                "snapshot_timestamp": self.snapshot_timestamp,
                "source_selection_policy": "pit-v1",
                "coverage_profile": "us-gaap-public-v1",
                "data_release_manifest_digest": None,
                "quality": "verified",
                "issue_codes": [],
                "provenance": {
                    "snapshot_id": "snapshot-aapl-resolved",
                    "mapping_version": "mapping-v1",
                    "parser_version": "parser-v1",
                    "taxonomy_version": "taxonomy-v1",
                    "policy_version": "pit-v1",
                },
            }
        return await super().execute(operation, input_payload, **kwargs)


@pytest.mark.asyncio
async def test_cutover_resolves_snapshot_and_facts_through_service_boundary() -> None:
    client = _Client(facts_ids=["fact-revenue"])
    runtime = _Runtime()
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
    started_at = datetime.now(UTC)
    try:
        result = await run_service_valuation_flow(
            runtime,
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
    assert client.deadlines
    assert (
        timedelta(seconds=110)
        < client.deadlines[0] - started_at
        < timedelta(seconds=130)
    )
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
    assert result.update["artifact_references"]["financial_reports"]["artifact_id"] == (
        "service-valuation-artifact"
    )
    output_artifact = result.update["fundamental_analysis"]["artifact"]
    assert output_artifact["kind"] == "fundamental_analysis.output"
    assert output_artifact["version"] == "v1"
    assert (
        output_artifact["reference"]
        == result.update["artifact_references"]["financial_reports"]
    )
    artifact = runtime.saved_calls[0]["data"]
    assert isinstance(artifact, dict)
    stored_artifact = FinancialReportsArtifactData.model_validate(artifact)
    assert stored_artifact.financial_reports == []
    service_artifact = artifact["fundamental_service"]
    assert isinstance(service_artifact, dict)
    assert service_artifact["projection_type"] == "valuation"
    assert service_artifact["facts"]["snapshot_id"] == "snapshot-resolved"
    fact_projection = service_artifact["facts"]["facts"][0]
    assert fact_projection["period_end"] == "2025-09-27"
    assert fact_projection["context"]["instant"] == "2025-09-27"
    assert "period" not in fact_projection
    assert service_artifact["valuation_trace"]["fact_ids"] == ["fact-revenue"]
    assert service_artifact["provenance"]["snapshot_id"] == "snapshot-resolved"
    assert service_artifact["hashes"]["snapshot_manifest_digest"] == "e" * 64


@pytest.mark.asyncio
async def test_cutover_binds_release_digest_to_context_without_provenance_leak() -> (
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
    release_digest = "c" * 64
    client = _Client(
        resolved_snapshot={
            "contract_version": "fundamental.v1",
            "snapshot_id": "snapshot-released",
            "historical_facts": ["fact-revenue"],
            "identity": payload["identity"],
            "valuation_timestamp": payload["valuation_context"]["valuation_timestamp"],
            "snapshot_timestamp": "2026-11-03T00:00:00Z",
            "source_selection_policy": "pit-v1",
            "coverage_profile": "us-gaap-public-v1",
            "data_release_manifest_digest": release_digest,
            "quality": "verified",
            "issue_codes": [],
            "provenance": {
                "snapshot_id": "snapshot-released",
                "mapping_version": "mapping-v1",
                "parser_version": "parser-v1",
                "taxonomy_version": "taxonomy-v1",
                "policy_version": "pit-v1",
                "data_release_manifest_digest": release_digest,
            },
        }
    )
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        await run_service_valuation_flow(
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
    validated = client.calls[1][1]
    assert validated["valuation_context"]["data_release_manifest_digest"] == (
        release_digest
    )
    assert "data_release_manifest_digest" not in validated["provenance"]
    assert client.calls[2][1]["valuation_context"]["data_release_manifest_digest"] == (
        release_digest
    )


@pytest.mark.asyncio
async def test_cutover_enriches_compact_caller_request_before_snapshot_resolution() -> (
    None
):
    client = _FactsOnlyClient(snapshot_timestamp="2026-11-01T00:00:00Z")
    runtime = _Runtime()
    compact = {
        "assumptions": {"terminal_growth": "0.02"},
        "uncertainty": {"mode": "none"},
        "requested_as_of": "2026-11-04T00:00:00Z",
    }
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            runtime,
            {
                "valuation_request": compact,
                "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
                "fundamental_analysis": {"model_type": "dcf_standard"},
            },
            client=client,
            request_approval_fn=lambda _request: {
                "type": "valuation_approval",
                "contract_version": "v1",
                "decision": "approve",
            },
            clock=lambda: datetime(2026, 11, 4, tzinfo=UTC),
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "ingest_sec_data",
        "resolve_snapshot",
        "validate_with_policy",
        "calculate",
    ]
    assert client.calls[1][1]["identity"]["issuer_id"] == "0000320193"
    assert client.calls[2][1]["required_fields"] == [
        "revenue",
        "operating_income",
        "cash",
        "debt",
        "diluted_shares",
    ]
    assert client.calls[3][1]["historical_facts"] == _FactsOnlyClient._fact_ids
    assert client.calls[3][1]["assumptions"] == compact["assumptions"]
    assert result.update["fundamental_analysis"]["valuation_status"] == "completed"


@pytest.mark.asyncio
async def test_cutover_publishes_snapshot_facts_without_fabricating_valuation() -> None:
    client = _FactsOnlyClient(snapshot_timestamp="2026-11-01T00:00:00Z")
    runtime = _Runtime()
    approval_calls: list[object] = []
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            runtime,
            {
                "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
                "fundamental_analysis": {"model_type": "dcf_standard"},
            },
            client=client,
            request_approval_fn=lambda request: approval_calls.append(request),
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "resolve_snapshot",
    ]
    assert client.facts_calls == [
        {
            "contract_version": "fundamental.v1",
            "snapshot_id": "snapshot-aapl-resolved",
            "data_release_manifest_digest": None,
            "required_fields": [
                "revenue",
                "operating_income",
                "cash",
                "debt",
                "diluted_shares",
            ],
        }
    ]
    assert approval_calls == []
    assert result.update["fundamental_analysis"]["valuation_status"] == "not_requested"
    assert result.update["fundamental_analysis"]["quality_status"] == "verified"
    assert result.update["artifact_references"]["financial_reports"]["artifact_id"] == (
        "service-valuation-artifact"
    )
    output_artifact = result.update["fundamental_analysis"]["artifact"]
    assert output_artifact["kind"] == "fundamental_analysis.output"
    assert output_artifact["version"] == "v1"
    assert output_artifact["preview"] is None
    assert (
        output_artifact["reference"]
        == result.update["artifact_references"]["financial_reports"]
    )

    artifact = runtime.saved_calls[0]["data"]
    assert isinstance(artifact, dict)
    FinancialReportsArtifactData.model_validate(artifact)
    service_artifact = artifact["fundamental_service"]
    assert isinstance(service_artifact, dict)
    assert service_artifact["projection_type"] == "facts_only"
    assert service_artifact["valuation_status"] == "not_requested"
    assert service_artifact["snapshot_id"] == "snapshot-aapl-resolved"
    assert service_artifact["snapshot_timestamp"] == "2026-11-01T00:00:00Z"
    assert service_artifact["fact_ids"] == _FactsOnlyClient._fact_ids
    assert "valuation_trace" not in service_artifact
    assert "valuation_input" not in service_artifact
    assert artifact["financial_reports"] == []


@pytest.mark.asyncio
async def test_production_orchestrator_persists_facts_artifact() -> None:
    client = _FactsOnlyClient(snapshot_timestamp="2026-11-01T00:00:00Z")
    storage = _ArtifactStorage()
    orchestrator = FundamentalOrchestrator(artifact_storage=storage)
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await orchestrator.run_service_valuation(
            {
                "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
                "fundamental_analysis": {"model_type": "dcf_standard"},
            },
            client=client,
            request_approval_fn=lambda request: pytest.fail(
                "facts-only reporting must not request valuation approval"
            ),
        )
    finally:
        reset_request_principal(token)

    assert len(storage.saved_calls) == 1
    saved = storage.saved_calls[0]
    assert saved["artifact_type"] == "financial_reports"
    assert saved["produced_by"] == "fundamental_analysis.service_facts"
    assert saved["key_prefix"] == "fundamental_service_facts"
    artifact = saved["data"]
    assert isinstance(artifact, dict)
    FinancialReportsArtifactData.model_validate(artifact)
    assert result.update["artifact_references"]["financial_reports"]["artifact_id"] == (
        "production-service-facts-artifact"
    )


@pytest.mark.parametrize(
    "client_options",
    (
        {"facts_snapshot_id": "snapshot-aapl-other"},
        {"facts_ids": ["fact-revenue"]},
    ),
)
@pytest.mark.asyncio
async def test_cutover_rejects_facts_outside_the_resolved_snapshot(
    client_options: Mapping[str, object],
) -> None:
    client = _FactsOnlyClient(**client_options)
    runtime = _Runtime()
    token = set_request_principal(
        InternalPrincipal(
            subject_id="caller-1", organization_id="org-1", membership_id="membership-1"
        )
    )
    try:
        result = await run_service_valuation_flow(
            runtime,
            {
                "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
                "fundamental_analysis": {"model_type": "dcf_standard"},
            },
            client=client,
            request_approval_fn=lambda _request: pytest.fail(
                "facts-only reporting must not request valuation approval"
            ),
            clock=lambda: datetime(2026, 11, 4, tzinfo=UTC),
        )
    finally:
        reset_request_principal(token)

    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "resolve_snapshot",
    ]
    assert len(client.facts_calls) == 1
    assert result.update["fundamental_analysis"]["valuation_status"] == (
        "service_unavailable"
    )
    assert result.update["fundamental_analysis"]["service_failure"]["code"] == (
        "UPSTREAM_MALFORMED"
    )
    assert runtime.saved_calls == []
    assert (
        result.update["fundamental_analysis"]["request_timing"]["valuation_timestamp"]
        == "2026-11-04T00:00:00Z"
    )
    assert result.update["fundamental_analysis"]["request_timing"][
        "fiscal_period_selector"
    ] == {
        "version": "fundamental.fiscal-period-selector.v1",
        "mode": "latest_complete",
        "count": 3,
    }


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
