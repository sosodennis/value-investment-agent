from __future__ import annotations

import pytest

from src.agents.fundamental.core_valuation.domain.report_contract import (
    parse_domain_financial_reports,
)
from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)


def test_parse_domain_financial_reports_rejects_scalar_field_fallback() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.base.fiscal_year must be a traceable object",
    ):
        parse_domain_financial_reports(
            [
                {
                    "industry_type": "Industrial",
                    "base": {
                        "fiscal_year": "2024",
                    },
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_extension_without_type() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.extension requires extension_type in canonical payload",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {"fiscal_year": {"value": "2024"}},
                    "extension": {"capex": {"value": 10.0}},
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_boolean_traceable_value() -> None:
    with pytest.raises(TypeError, match="financial report.base.fiscal_year.value"):
        parse_domain_financial_reports(
            [
                {
                    "base": {
                        "fiscal_year": {
                            "value": True,
                        }
                    }
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_industry_type_extension_fallback() -> (
    None
):
    with pytest.raises(
        TypeError,
        match="financial report.extension requires extension_type in canonical payload",
    ):
        parse_domain_financial_reports(
            [
                {
                    "industry_type": "Industrial",
                    "base": {"fiscal_year": {"value": "2024"}},
                    "extension": {"capex": {"value": 10.0}},
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_unknown_provenance_shape() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.base.fiscal_year.provenance has unsupported shape",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {
                        "fiscal_year": {
                            "value": "2024",
                            "provenance": {"foo": "bar"},
                        }
                    }
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_incompatible_provenance_type() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.base.fiscal_year.provenance payload is incompatible",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {
                        "fiscal_year": {
                            "value": "2024",
                            "provenance": {
                                "type": "XBRL",
                                "description": "manual provenance shape",
                            },
                        }
                    }
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_domain_object_input() -> None:
    with pytest.raises(TypeError, match="unsupported type"):
        parse_domain_financial_reports([object()])  # type: ignore[list-item]


def test_parse_domain_financial_reports_requires_provenance() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.base.fiscal_year.provenance is required",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {
                        "fiscal_year": {
                            "value": "2024",
                        }
                    }
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_traceable_object_input() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.base.fiscal_year must be a traceable object",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {
                        "fiscal_year": TraceableField(
                            name="Fiscal Year",
                            value="2024",
                            provenance=ManualProvenance(description="test"),
                        )
                    }
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_provenance_object_input() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.base.fiscal_year.provenance must be an object",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {
                        "fiscal_year": {
                            "value": "2024",
                            "provenance": ManualProvenance(description="test"),
                        }
                    }
                }
            ]
        )


def test_parse_domain_financial_reports_rejects_legacy_extension_type_token() -> None:
    with pytest.raises(
        TypeError,
        match="financial report.extension_type must be canonical token",
    ):
        parse_domain_financial_reports(
            [
                {
                    "base": {"fiscal_year": {"value": "2024"}},
                    "extension_type": "Financial",
                }
            ]
        )
