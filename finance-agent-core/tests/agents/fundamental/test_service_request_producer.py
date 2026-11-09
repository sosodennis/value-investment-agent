from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.agents.fundamental.application.workflow_orchestrator.services.service_request_producer import (
    prepare_service_valuation_request,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalIdentityResolutionV1,
    FundamentalServiceResponseV1,
    FundamentalValuationPreparationResultV1,
)
from src.agents.fundamental.interface.request_contracts import (
    FundamentalRequestTimingV1,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.internal_services import InternalPrincipal


class _Client:
    def __init__(self, *, ingestion: Mapping[str, object]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.ingestion = dict(ingestion)
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
                    "data_release_manifest_digest": self.ingestion["manifest_digest"],
                    "historical_facts": self.ingestion["canonical_fact_ids"],
                    "identity": input_payload["identity"],
                    "valuation_timestamp": input_payload["valuation_timestamp"],
                    "snapshot_timestamp": input_payload["valuation_timestamp"],
                    "source_selection_policy": input_payload["source_selection_policy"],
                    "coverage_profile": input_payload["coverage_profile"],
                    "quality": "verified",
                    "issue_codes": [],
                    "provenance": {
                        "snapshot_id": "snapshot-aapl-1",
                        "data_release_manifest_digest": self.ingestion[
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
        result = {
            **self.ingestion,
            "valuation_timestamp": input_payload["valuation_timestamp"],
        }
        return FundamentalServiceResponseV1(
            contract_version="internal.v1",
            schema_version="fundamental.v1",
            correlation_id="correlation-1",
            result=result,
        )

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
                "coverage_profile": "fcff-valuation-requirements-v1",
            },
            "historical_facts": list(self.ingestion["canonical_fact_ids"]),
            "assumptions": {
                "forecast": {"base_revenue": "100"},
                "trace": {"description": "service-owned fixture assumptions"},
            },
            "uncertainty": {"mode": "none"},
            "quality": {"status": "provisional"},
            "provenance": {
                "snapshot_id": input_payload["snapshot_id"],
                "fact_ids": list(self.ingestion["canonical_fact_ids"]),
                "mapping_version": "sec-us-gaap-v1",
                "parser_version": "2.47.4",
                "taxonomy_version": "us-gaap-2023-2024",
                "policy_version": "sec-public-pit-v1",
            },
            "model_id": input_payload["model_id"],
            "model_version": "fcff_dcf-v1",
            "policy_id": "fcff_dcf-us-gaap-public-v1",
            "input_digest": None,
        }
        self.calls.append(("prepare_valuation", dict(input_payload)))
        self.last_preparation = FundamentalValuationPreparationResultV1.model_validate(
            {
                "contract_version": "fundamental.v1",
                "status": "prepared",
                "model_id": input_payload["model_id"],
                "model_version": "fcff_dcf-v1",
                "profile_id": "fcff-valuation-requirements-v1",
                "profile_digest": "d" * 64,
                "policy_id": "fcff_dcf-us-gaap-public-v1",
                "policy_version": "fcff_dcf-v1-quality-v1",
                "quality_status": "provisional",
                "issue_codes": ["HISTORY_THRESHOLD_UNVALIDATED"],
                "missing_evidence": [],
                "historical_metrics": {},
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


def _ingestion(*, status: str = "created") -> dict[str, object]:
    return {
        "contract_version": "fundamental.v1",
        "status": status,
        "identity": {
            "issuer_id": "0000320193",
            "issuer_name": "Apple Inc.",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "security_id": "AAPL",
            "share_class": "AAPL",
            "currency": "USD",
        },
        "valuation_timestamp": "2026-11-07T00:00:00Z",
        "snapshot_id": "snapshot-aapl-1",
        "manifest_digest": "b" * 64,
        "canonical_fact_ids": ["fact-revenue", "fact-operating-income"],
        "quality_status": "verified",
        "parser_version": "2.47.4",
        "validation_profile_id": "sec-efm-us-dqc-v31.0.3",
        "validation_profile_digest": "c" * 64,
        "taxonomy_manifest_id": "sec-us-gaap-2023-2024-public-bundle",
        "taxonomy_version": "us-gaap-2023-2024",
        "reused": status == "reused",
        "coalesced": False,
        "correlation_id": "correlation-1",
    }


def _state(
    *,
    request: Mapping[str, object] | None = None,
    model_type: str = "dcf_standard",
) -> dict[str, object]:
    fundamental: dict[str, object] = {"model_type": model_type}
    if request is not None:
        fundamental["valuation_request"] = dict(request)
    return {
        "company_profile": CompanyProfile(ticker="AAPL", name="Apple Inc."),
        "fundamental_analysis": fundamental,
    }


def _request() -> dict[str, object]:
    return {
        "contract_version": "fundamental.v1",
        "valuation_context": {
            "valuation_timestamp": "2026-11-07T00:00:00Z",
            "source_selection_policy": "pit-v1",
            "coverage_profile": "us-gaap-public-v1",
        },
        "assumptions": {"trace": {"description": "caller-owned"}},
        "uncertainty": {"mode": "none"},
        "quality": {"status": "verified"},
        "provenance": {
            "snapshot_id": "pending",
            "fact_ids": [],
            "mapping_version": "sec-us-gaap-v1",
            "parser_version": "2.47.4",
            "taxonomy_version": "us-gaap-2023-2024",
            "policy_version": "sec-public-pit-v1",
        },
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v1",
        "policy_id": "fcff_dcf-us-gaap-public-v1",
    }


def _compact_request() -> dict[str, object]:
    return {
        "assumptions": {"trace": {"description": "caller-owned"}},
        "uncertainty": {"mode": "none"},
        "requested_as_of": "2026-11-07T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_producer_resolves_identity_then_ingests_and_pins_request() -> None:
    client = _Client(ingestion=_ingestion())

    prepared = await prepare_service_valuation_request(
        _state(request=_request()),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "ingest_sec_data",
    ]
    ingestion_payload = client.calls[1][1]
    assert ingestion_payload["cik"] == "0000320193"
    assert ingestion_payload["ticker"] == "AAPL"
    assert ingestion_payload["required_fields"] == [
        "revenue",
        "cost_of_revenue",
        "operating_income",
        "income_before_tax",
        "income_tax_expense",
        "net_income",
        "depreciation_and_amortization",
        "capital_expenditure",
        "operating_lease_cost",
        "finance_lease_cost",
        "stock_based_compensation",
        "basic_weighted_average_shares",
        "diluted_weighted_average_shares",
        "operating_current_receivables",
        "inventory",
        "contract_assets",
        "operating_current_payables",
        "accrued_operating_liabilities",
        "deferred_revenue",
        "cash_and_equivalents",
        "current_interest_bearing_debt",
        "long_term_interest_bearing_debt",
        "current_operating_lease_liabilities",
        "long_term_operating_lease_liabilities",
        "current_finance_lease_liabilities",
        "long_term_finance_lease_liabilities",
        "preferred_claims",
        "noncontrolling_interests",
        "convertible_instruments",
        "common_shares_outstanding",
        "dilutive_instruments",
        "other_share_classes",
    ]
    assert prepared.snapshot_selector["identity"] == prepared.identity
    assert prepared.snapshot_selector["release_profile_id"] == "sec-public-pit-v1"
    assert prepared.snapshot_selector["valuation_timestamp"] == "2026-11-07T00:00:00Z"
    assert prepared.valuation_request is not None
    assert prepared.valuation_request["historical_facts"] == [
        "fact-revenue",
        "fact-operating-income",
    ]
    assert prepared.valuation_request["identity"] == prepared.identity


@pytest.mark.asyncio
async def test_producer_enriches_compact_caller_request_without_inventing_inputs() -> (
    None
):
    client = _Client(ingestion=_ingestion())

    prepared = await prepare_service_valuation_request(
        _state(request=_compact_request()),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert prepared.valuation_request is not None
    assert prepared.valuation_request["assumptions"]["trace"]["description"] == (
        "service-owned fixture assumptions"
    )
    assert prepared.valuation_request["model_id"] == "fcff_dcf"
    assert prepared.valuation_request["model_version"] == "fcff_dcf-v1"
    assert prepared.valuation_request["policy_id"] == "fcff_dcf-us-gaap-public-v1"
    assert prepared.valuation_request["quality"] == {"status": "provisional"}
    assert prepared.valuation_request["provenance"] == {
        "snapshot_id": "snapshot-aapl-1",
        "fact_ids": ["fact-revenue", "fact-operating-income"],
        "mapping_version": "sec-us-gaap-v1",
        "parser_version": "2.47.4",
        "taxonomy_version": "us-gaap-2023-2024",
        "policy_version": "sec-public-pit-v1",
    }
    assert "fiscal_period_selector" not in prepared.snapshot_selector
    assert prepared.valuation_request["valuation_context"] == {
        "valuation_timestamp": "2026-11-07T00:00:00Z",
        "data_snapshot_id": "snapshot-aapl-1",
        "data_release_manifest_digest": "b" * 64,
        "source_selection_policy": "pit-v1",
        "coverage_profile": "fcff-valuation-requirements-v1",
    }
    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "ingest_sec_data",
        "resolve_snapshot",
        "prepare_valuation",
    ]


@pytest.mark.asyncio
async def test_producer_routes_manual_override_back_through_fundamental_service() -> (
    None
):
    client = _Client(ingestion=_ingestion())
    request = _compact_request()
    request["manual_override"] = {
        "contract_version": "fundamental.v1",
        "path": "assumptions.forecast.base_revenue",
        "value": "110",
        "provenance": {
            "author": "workspace-user",
            "modified_at": "2026-11-07T00:00:00Z",
            "reason": "Updated the base year after reviewing the filing.",
            "automatic_preparation_digest": "e" * 64,
        },
    }

    prepared = await prepare_service_valuation_request(
        _state(request=request),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert prepared.valuation_request is not None
    assert [operation for operation, _ in client.calls] == [
        "resolve_identity",
        "ingest_sec_data",
        "resolve_snapshot",
        "prepare_valuation",
        "override_prepared_valuation",
    ]
    override_payload = client.calls[-1][1]
    assert override_payload["path"] == "assumptions.forecast.base_revenue"
    assert override_payload["value"] == "110"


@pytest.mark.asyncio
async def test_transition_request_adds_filed_evidence_to_complete_profile() -> None:
    client = _Client(ingestion=_ingestion())

    await prepare_service_valuation_request(
        _state(request=_compact_request(), model_type="dcf_growth"),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    ingestion_payload = client.calls[1][1]
    assert ingestion_payload["required_fields"][-1] == "filed_operating_evidence"
    assert len(ingestion_payload["required_fields"]) == 33


@pytest.mark.asyncio
async def test_producer_preserves_explicit_fiscal_period_selector() -> None:
    client = _Client(ingestion=_ingestion())
    request = _compact_request()
    request["valuation_context"] = {
        "fiscal_period_selector": {
            "mode": "latest_complete",
            "count": 1,
        }
    }

    prepared = await prepare_service_valuation_request(
        _state(request=request),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        request_timing=FundamentalRequestTimingV1.accept(
            request,
            clock=lambda: datetime(2026, 11, 7, tzinfo=UTC),
        ),
    )

    assert prepared.snapshot_selector["fiscal_period_selector"] == {
        "version": "fundamental.fiscal-period-selector.v1",
        "mode": "latest_complete",
        "count": 1,
    }
    assert prepared.valuation_request is not None
    assert prepared.valuation_request["valuation_context"][
        "fiscal_period_selector"
    ] == {
        "version": "fundamental.fiscal-period-selector.v1",
        "mode": "latest_complete",
        "count": 1,
    }


@pytest.mark.asyncio
async def test_producer_returns_explicit_missing_assumptions_reason() -> None:
    client = _Client(ingestion=_ingestion())

    prepared = await prepare_service_valuation_request(
        _state(),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert prepared.valuation_request is None
    assert prepared.reason == "caller valuation assumptions are required"
    assert prepared.ingestion == {}
    assert prepared.snapshot_selector["release_profile_id"] == "sec-public-pit-v1"
    assert "fiscal_period_selector" not in prepared.snapshot_selector
    assert [operation for operation, _ in client.calls] == ["resolve_identity"]


@pytest.mark.asyncio
async def test_facts_only_request_uses_accepted_timestamp_without_ingestion_or_fiscal_selector() -> (
    None
):
    client = _Client(ingestion=_ingestion())
    timing = FundamentalRequestTimingV1.accept(
        {}, clock=lambda: datetime(2026, 11, 8, 0, 0, tzinfo=UTC)
    )

    prepared = await prepare_service_valuation_request(
        _state(),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 8, tzinfo=UTC),
        request_timing=timing,
    )

    assert prepared.valuation_request is None
    assert prepared.ingestion == {}
    assert prepared.snapshot_selector["valuation_timestamp"] == ("2026-11-08T00:00:00Z")
    assert "fiscal_period_selector" not in prepared.snapshot_selector
    assert [operation for operation, _ in client.calls] == ["resolve_identity"]


@pytest.mark.asyncio
async def test_facts_only_projection_uses_base_evidence_for_growth_model() -> None:
    client = _Client(ingestion=_ingestion())

    prepared = await prepare_service_valuation_request(
        _state(model_type="dcf_growth"),
        client=client,
        principal=_principal(),
        correlation_id="correlation-1",
        deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    assert prepared.valuation_request is None
    assert prepared.snapshot_selector["required_fields"] == [
        "revenue",
        "cost_of_revenue",
        "operating_income",
        "income_before_tax",
        "income_tax_expense",
        "net_income",
        "depreciation_and_amortization",
        "capital_expenditure",
        "operating_lease_cost",
        "finance_lease_cost",
        "stock_based_compensation",
        "basic_weighted_average_shares",
        "diluted_weighted_average_shares",
        "operating_current_receivables",
        "inventory",
        "contract_assets",
        "operating_current_payables",
        "accrued_operating_liabilities",
        "deferred_revenue",
        "cash_and_equivalents",
        "current_interest_bearing_debt",
        "long_term_interest_bearing_debt",
        "current_operating_lease_liabilities",
        "long_term_operating_lease_liabilities",
        "current_finance_lease_liabilities",
        "long_term_finance_lease_liabilities",
        "preferred_claims",
        "noncontrolling_interests",
        "convertible_instruments",
        "common_shares_outstanding",
        "dilutive_instruments",
        "other_share_classes",
    ]
    assert [operation for operation, _ in client.calls] == ["resolve_identity"]


@pytest.mark.asyncio
async def test_producer_rejects_identity_mismatch_before_ingestion() -> None:
    client = _Client(ingestion=_ingestion())
    request = _request()
    request["identity"] = {"issuer_id": "0000000001"}

    with pytest.raises(FundamentalServiceFailure, match="identity") as error:
        await prepare_service_valuation_request(
            _state(request=request),
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )

    assert error.value.code == "IDENTITY_MISMATCH"
    assert [operation for operation, _ in client.calls] == ["resolve_identity"]


@pytest.mark.asyncio
async def test_producer_rejects_degraded_ingestion_without_snapshot() -> None:
    client = _Client(ingestion=_ingestion(status="degraded"))

    with pytest.raises(FundamentalServiceFailure) as error:
        await prepare_service_valuation_request(
            _state(request=_request()),
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )

    assert error.value.code == "SEC_INGESTION_DEGRADED"


@pytest.mark.asyncio
async def test_producer_rejects_missing_ticker_without_service_calls() -> None:
    client = _Client(ingestion=_ingestion())

    with pytest.raises(FundamentalServiceFailure) as error:
        await prepare_service_valuation_request(
            {"company_profile": None, "fundamental_analysis": {}},
            client=client,
            principal=_principal(),
            correlation_id="correlation-1",
            deadline_at=datetime(2026, 11, 7, tzinfo=UTC),
        )

    assert error.value.code == "FUNDAMENTAL_TICKER_MISSING"
    assert client.calls == []
