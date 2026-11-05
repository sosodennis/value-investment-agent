import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fundamental_service.app import create_app
from fundamental_service.bank_model import (
    bank_artifact_findings,
    calculate_bank_excess_return,
    independent_bank_reference,
)
from fundamental_service.bank_source import (
    bank_report_issuer_mapping_status,
    parse_fdic_bankfind_report,
)
from fundamental_service.contracts import (
    AssumptionsV1,
    BankAssumptionsV1,
    SourceRecordV1,
    SourceRole,
    ValuationInputV1,
)
from fundamental_service.testsupport import (
    auth_headers,
    make_internal_envelope,
    make_valuation,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "public-sources"
REPORT_FIXTURE = "fdic-jpmorgan-financials-20260630.json"


def fdic_source(payload: bytes | None = None) -> SourceRecordV1:
    body = payload or (FIXTURE_ROOT / REPORT_FIXTURE).read_bytes()
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    record = next(
        item for item in manifest["sources"] if item["path"].endswith(REPORT_FIXTURE)
    )
    return SourceRecordV1(
        source_id=record["source_id"],
        uri=record["uri"],
        role=SourceRole(record["role"]),
        available_at=datetime.fromisoformat(record["available_at"]),
        captured_at=datetime.fromisoformat(record["available_at"]),
        publication_at=datetime.fromisoformat(record["publication_at"]),
        http_status=record["http_status"],
        media_type=record["media_type"],
        terms_reference=record["terms_reference"],
        content_hash=hashlib.sha256(body).hexdigest(),
        parser_version="fdic-bankfind-v1",
    )


def bank_valuation(
    *,
    minimum_cet1_ratio: Decimal = Decimal("0.08"),
    forecast_rwa_growth: tuple[Decimal, Decimal, Decimal] = (
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.02"),
    ),
) -> ValuationInputV1:
    refs = {
        "current_book_value": "fact-bank-book-value",
        "tangible_book_value": "fact-bank-tangible-book-value",
        "reported_rwa": "fact-bank-rwa",
        "cet1_capital": "fact-bank-cet1",
        "diluted_shares": "fact-bank-shares",
        "regulatory_entity": "fact-bank-regulatory-entity",
        "issuer_entity_relationship": "fact-bank-issuer-relationship",
    }
    base = make_valuation()
    raw = base.model_dump()
    raw.update(
        {
            "model_id": "bank_excess_return",
            "model_version": "bank_excess_return-v1",
            "historical_facts": tuple(refs.values()),
            "assumptions": AssumptionsV1(
                bank=BankAssumptionsV1(
                    current_book_value=Decimal("1000"),
                    tangible_book_value=Decimal("800"),
                    forecast_net_income=(
                        Decimal("100"),
                        Decimal("110"),
                        Decimal("120"),
                    ),
                    forecast_rwa_growth=forecast_rwa_growth,
                    cost_of_equity=Decimal("0.10"),
                    payout_ratio=Decimal("0.40"),
                    terminal_growth=Decimal("0.02"),
                    reported_rwa=Decimal("5000"),
                    cet1_capital=Decimal("500"),
                    minimum_cet1_ratio=minimum_cet1_ratio,
                    fdic_certificate="628",
                    reporting_entity_relationship="same_legal_entity",
                    fact_references=refs,
                    diluted_shares=Decimal("100"),
                    trace={"description": "explicit bank model fixture"},
                )
            ).model_dump(),
            "input_digest": None,
            "caller_approval": None,
        }
    )
    return ValuationInputV1.model_validate(raw)


def test_captured_fdic_report_does_not_claim_issuer_mapping():
    payload = (FIXTURE_ROOT / REPORT_FIXTURE).read_bytes()
    report = parse_fdic_bankfind_report(
        payload, source=fdic_source(payload), expected_certificate="628"
    )
    assert report.institution_name == "JPMORGAN CHASE BANK NA"
    assert report.report_date.isoformat() == "2026-06-30"
    assert report.risk_weighted_assets == Decimal("2013590745")
    assert report.cet1_ratio == Decimal("15.027333670030352") / Decimal("100")
    status, issues = bank_report_issuer_mapping_status(
        report=report, issuer_id="CIK0000019617"
    )
    assert status == "unsupported"
    assert issues == ("BANK_REGULATORY_ENTITY_MAPPING_NOT_RELEASED",)


def test_fdic_parser_rejects_hash_and_certificate_mismatch():
    payload = (FIXTURE_ROOT / REPORT_FIXTURE).read_bytes()
    source = fdic_source(payload)
    with pytest.raises(ValueError, match="certificate"):
        parse_fdic_bankfind_report(payload, source=source, expected_certificate="999")
    with pytest.raises(ValueError, match="hash"):
        parse_fdic_bankfind_report(
            payload + b" ", source=source, expected_certificate="628"
        )


def test_research_bank_calculator_matches_separate_challenger_by_node():
    request = bank_valuation().with_digest()
    artifact = calculate_bank_excess_return(request)
    equity, per_share, expected = independent_bank_reference(request)
    assert artifact.intrinsic_value == equity
    assert artifact.per_share_value == per_share
    assert bank_artifact_findings(request, artifact) == ()
    actual = {node.node_id: node.value for node in artifact.nodes}
    assert all(actual[node_id] == value for node_id, value in expected.items())
    terminal_book = next(
        node for node in artifact.nodes if node.node_id == "bank_terminal_book_value"
    )
    assert terminal_book.formula == "ending_book_value_at_forecast_horizon"
    assert terminal_book.inputs == ("bank_book_value_3",)
    equity_node = next(
        node for node in artifact.nodes if node.node_id == "bank_equity_value"
    )
    assert equity_node.inputs[0] == "bank_tangible_book_value"
    assert artifact.result_hash == calculate_bank_excess_return(request).result_hash


def test_research_bank_calculator_abstains_when_forecast_breaches_cet1_floor():
    request = bank_valuation(
        minimum_cet1_ratio=Decimal("0.09"),
        forecast_rwa_growth=(Decimal("0.20"), Decimal("0.20"), Decimal("0.20")),
    )
    with pytest.raises(ValueError, match="below the caller's declared floor"):
        calculate_bank_excess_return(request)


def test_bank_references_must_be_in_the_selected_valuation_snapshot():
    raw = bank_valuation().model_dump()
    raw["historical_facts"] = raw["historical_facts"][:-1]
    with pytest.raises(ValueError, match="belong to historical_facts"):
        ValuationInputV1.model_validate(raw)


def test_valuation_schema_declares_model_specific_assumption_requirements():
    schema = ValuationInputV1.model_json_schema()
    bank_rule = next(
        rule
        for rule in schema["allOf"]
        if rule["if"]["properties"]["model_id"].get("const") == "bank_excess_return"
    )
    fcff_rule = next(
        rule
        for rule in schema["allOf"]
        if "fcff_dcf" in rule["if"]["properties"]["model_id"].get("enum", [])
    )

    bank_assumptions = bank_rule["then"]["properties"]["assumptions"]
    assert bank_assumptions["required"] == ["bank"]
    assert bank_assumptions["properties"]["bank"] == {"not": {"type": "null"}}
    assert all(
        bank_assumptions["properties"][field] == {"type": "null"}
        for field in ("forecast", "wacc", "terminal_growth", "capital_bridge", "trace")
    )

    fcff_assumptions = fcff_rule["then"]["properties"]["assumptions"]
    assert set(fcff_assumptions["required"]) == {
        "forecast",
        "wacc",
        "terminal_growth",
        "capital_bridge",
        "trace",
    }
    assert all(
        fcff_assumptions["properties"][field] == {"not": {"type": "null"}}
        for field in fcff_assumptions["required"]
    )


def test_bank_contract_rejects_fcff_assumptions():
    raw = bank_valuation().model_dump()
    raw["assumptions"]["trace"] = {"description": "must remain family scoped"}
    with pytest.raises(ValueError, match="FCFF-specific assumptions"):
        ValuationInputV1.model_validate(raw)


@pytest.mark.parametrize(
    "model_id",
    (
        "bank_excess_return",
        "insurance_statutory_excess_return",
        "reit_nav",
        "regulated_utility",
        "normalized_cyclical",
        "biotech_rnpv",
        "sum_of_parts",
        "ifrs_fcff_dcf",
    ),
)
def test_http_contract_reports_unreleased_families_as_unsupported(model_id: str):
    base_request = (
        bank_valuation()
        if model_id == "bank_excess_return"
        else make_valuation().model_copy(
            update={"model_id": model_id, "assumptions": AssumptionsV1()}
        )
    )
    request = base_request.model_copy(
        update={
            "valuation_context": make_valuation().valuation_context.model_copy(
                update={"data_snapshot_id": "snapshot-bank"}
            )
        }
    ).with_digest()

    class SnapshotRepository:
        def get(self, snapshot_id: str):
            raise AssertionError("unsupported models do not resolve source snapshots")

    class FactRepository:
        def get(self, fact_id: str):
            raise AssertionError("unsupported models do not resolve canonical facts")

    client = TestClient(
        create_app(SnapshotRepository(), fact_repository=FactRepository())
    )
    payload = request.model_dump(mode="json")
    envelope = make_internal_envelope(payload)
    validation = client.post(
        "/v1/valuation/validate", headers=auth_headers(), json=envelope
    )
    assert validation.status_code == 200
    assert validation.json()["result"]["quality_status"] == "unsupported"
    assert "MODEL_FAMILY_NOT_RELEASED" in validation.json()["result"]["issue_codes"]
    assert (
        "complete_model_source_cohort_challenger_calibration_release"
        in (validation.json()["result"]["missing_evidence"])
    )

    calculation = client.post(
        "/v1/valuation/calculate", headers=auth_headers(), json=envelope
    )
    assert calculation.status_code == 422
    assert calculation.json()["error"]["code"] == "MODEL_UNSUPPORTED"
