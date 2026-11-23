import json

import pytest
from pydantic import ValidationError

from src.shared.artifacts.fundamental_contracts import (
    FundamentalCalculationAssumptionsV1,
)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"forecast": None, "wacc": None},
        {
            "forecast": {
                "base_revenue": "1000000.0000000000001",
                "revenue_growth": ["0.05"],
                "nested": {"retained": None},
            },
            "wacc": {"beta": "1.2"},
        },
        {"forecast": {"timeline": None}, "opaque": [None, "1e400", 2]},
    ],
)
def test_retained_assumptions_preserve_exact_json_shape(payload):
    parsed = FundamentalCalculationAssumptionsV1.model_validate_json(
        json.dumps(payload)
    )
    assert parsed.model_dump(mode="json", warnings="error") == payload
    assert json.loads(parsed.model_dump_json(warnings="error")) == payload


def timeline():
    return {
        "policy_version": "fcff-uniform-accrual-period-end-act365f-v1",
        "calendar_basis": "source-month-end",
        "label_basis": "period-end-year",
        "valuation_date": "2026-11-23",
        "source_period_start": "2025-07-01",
        "source_period_end": "2026-06-30",
        "source_revenue_fact_id": "revenue-2026",
        "calendar_fact_ids": ["revenue-2024", "revenue-2025", "revenue-2026"],
        "periods": [
            {
                "ordinal": 1,
                "period_start": "2026-07-01",
                "period_end": "2027-06-30",
                "included_start": "2026-11-24",
                "cash_flow_date": "2027-06-30",
                "full_period_days": 365,
                "included_days": 219,
                "discount_days": 219,
            }
        ],
    }


def test_service_timeline_is_typed_without_recomputing_or_replacing_opaque_values():
    payload = {
        "forecast": {"timeline": timeline(), "base_revenue": "1e400"},
        "unchanged": {"raw": None},
    }
    parsed = FundamentalCalculationAssumptionsV1.model_validate_json(
        json.dumps(payload)
    )
    assert parsed.forecast.timeline.periods[0].period_end.isoformat() == "2027-06-30"
    assert parsed.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "mutation", ["invalid-date", "missing-period", "unexpected-field"]
)
def test_display_transport_rejects_malformed_timeline_shape(mutation):
    value = timeline()
    if mutation == "invalid-date":
        value["periods"][0]["period_end"] = "2027-02-30"
    elif mutation == "missing-period":
        del value["periods"][0]["included_days"]
    else:
        value["invented"] = True
    with pytest.raises(ValidationError):
        FundamentalCalculationAssumptionsV1.model_validate_json(
            json.dumps({"forecast": {"timeline": value}})
        )
