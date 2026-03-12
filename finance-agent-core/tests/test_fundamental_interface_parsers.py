from __future__ import annotations

import pytest

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    parse_financial_reports_model,
)
from src.agents.fundamental.subdomains.financial_statements.interface.parsers import (
    parse_calculation_metrics,
    parse_financial_statements_payload,
    parse_valuation_model_runtime,
)


def test_parse_valuation_model_runtime_accepts_mapping() -> None:
    class _AuditResult:
        passed = True
        messages: list[str] = []

    runtime = parse_valuation_model_runtime(
        {
            "schema": lambda **kwargs: kwargs,
            "calculator": lambda params: {"intrinsic_value": 1.0, "params": params},
            "auditor": lambda params: _AuditResult(),
        },
        context="fundamental model runtime",
    )
    assert callable(runtime.schema)
    assert callable(runtime.calculator)
    assert callable(runtime.auditor)


def test_parse_valuation_model_runtime_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        parse_valuation_model_runtime("invalid", context="fundamental model runtime")


def test_parse_valuation_model_runtime_rejects_missing_auditor() -> None:
    with pytest.raises(TypeError, match="auditor"):
        parse_valuation_model_runtime(
            {
                "schema": lambda **kwargs: kwargs,
                "calculator": lambda params: {"intrinsic_value": 1.0, "params": params},
            },
            context="fundamental model runtime",
        )


def test_parse_calculation_metrics_requires_object() -> None:
    parsed = parse_calculation_metrics(
        {"intrinsic_value": 12.3},
        context="valuation result",
    )
    assert parsed["intrinsic_value"] == 12.3

    with pytest.raises(TypeError):
        parse_calculation_metrics(["bad"], context="valuation result")


def test_parse_financial_reports_model_returns_json_dto_list() -> None:
    parsed = parse_financial_reports_model(
        [
            {
                "base": {},
                "industry_type": "Industrial",
                "extension_type": "Industrial",
                "extension": {},
            }
        ],
        context="financial reports",
    )
    assert isinstance(parsed, list)
    assert isinstance(parsed[0], dict)
    assert parsed[0]["industry_type"] == "Industrial"


def test_parse_financial_reports_model_rejects_non_list() -> None:
    with pytest.raises(TypeError):
        parse_financial_reports_model({"base": {}}, context="financial reports")


def test_parse_financial_reports_model_rejects_scalar_traceable_field() -> None:
    with pytest.raises(TypeError, match="traceable field must be an object"):
        parse_financial_reports_model(
            [
                {
                    "base": {"fiscal_year": "2024"},
                    "industry_type": "General",
                }
            ],
            context="financial reports",
        )


def test_parse_financial_reports_model_can_inject_default_provenance() -> None:
    parsed = parse_financial_reports_model(
        [
            {
                "base": {
                    "fiscal_year": {"value": "2024"},
                },
                "industry_type": "Industrial",
                "extension_type": "Industrial",
                "extension": {"capex": {"value": 10.0}},
            }
        ],
        context="financial reports",
        inject_default_provenance=True,
    )
    base_fiscal_year = parsed[0]["base"]["fiscal_year"]
    extension_capex = parsed[0]["extension"]["capex"]

    assert base_fiscal_year["provenance"]["type"] == "MANUAL"
    assert extension_capex["provenance"]["type"] == "MANUAL"


def test_parse_financial_reports_model_rejects_industry_type_extension_fallback() -> (
    None
):
    with pytest.raises(
        TypeError,
        match="financial report.extension requires extension_type in canonical payload",
    ):
        parse_financial_reports_model(
            [
                {
                    "base": {
                        "fiscal_year": {"value": "2024"},
                    },
                    "industry_type": "Industrial",
                    "extension": {"capex": {"value": 10.0}},
                }
            ],
            context="financial reports",
        )


def test_parse_financial_reports_model_rejects_legacy_industry_type_token() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.industry_type must be canonical token",
    ):
        parse_financial_reports_model(
            [
                {
                    "base": {"fiscal_year": {"value": "2024"}},
                    "industry_type": "Financial Services",
                }
            ],
            context="financial reports",
        )


def test_parse_financial_reports_model_rejects_legacy_extension_type_token() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.extension_type must be canonical token",
    ):
        parse_financial_reports_model(
            [
                {
                    "base": {"fiscal_year": {"value": "2024"}},
                    "extension_type": "Financial",
                }
            ],
            context="financial reports",
        )


def test_parse_financial_statements_payload_normalizes_reports() -> None:
    payload = parse_financial_statements_payload(
        {
            "financial_reports": [
                {
                    "base": {},
                    "industry_type": "Industrial",
                    "extension_type": "Industrial",
                    "extension": {},
                }
            ],
            "diagnostics": {"parser": "xbrl", "confidence": 0.9},
            "quality_gates": {"status": "pass", "blocking_count": 0},
        },
        context="financial_health.payload",
    )
    assert len(payload.financial_reports) == 1
    assert payload.financial_reports[0]["industry_type"] == "Industrial"
    assert payload.diagnostics == {"parser": "xbrl", "confidence": 0.9}
    assert payload.quality_gates == {"status": "pass", "blocking_count": 0}


def test_parse_financial_statements_payload_rejects_non_mapping() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        parse_financial_statements_payload(
            [
                {
                    "base": {},
                    "industry_type": "General",
                }
            ],
            context="financial_health.payload",
        )


def test_parse_financial_statements_payload_rejects_missing_required_key() -> None:
    with pytest.raises(
        TypeError,
        match="financial_health.payload.diagnostics is required",
    ):
        parse_financial_statements_payload(
            {
                "financial_reports": [],
                "quality_gates": None,
            },
            context="financial_health.payload",
        )
