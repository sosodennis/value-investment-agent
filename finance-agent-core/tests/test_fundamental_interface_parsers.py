from __future__ import annotations

import pytest

from src.agents.fundamental.interface.contracts import parse_financial_reports_model
from src.agents.fundamental.interface.parsers import (
    parse_calculation_metrics,
    parse_valuation_skill_runtime,
)


def test_parse_valuation_skill_runtime_accepts_mapping() -> None:
    runtime = parse_valuation_skill_runtime(
        {
            "schema": lambda **kwargs: kwargs,
            "calculator": lambda params: {"intrinsic_value": 1.0, "params": params},
        },
        context="fundamental skill",
    )
    assert callable(runtime.schema)
    assert callable(runtime.calculator)


def test_parse_valuation_skill_runtime_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        parse_valuation_skill_runtime("invalid", context="fundamental skill")


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
