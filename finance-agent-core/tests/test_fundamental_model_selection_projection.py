from __future__ import annotations

from src.agents.fundamental.data.mappers import project_selection_reports
from src.agents.fundamental.domain.model_selection import select_valuation_model
from src.agents.fundamental.domain.models import ValuationModel
from src.shared.domain.market_identity import CompanyProfile


def test_project_selection_reports_extracts_typed_fields() -> None:
    reports_raw = [
        {
            "base": {
                "sic_code": {"value": "6798"},
                "total_revenue": {"value": 1200.0},
                "net_income": {"value": 200.0},
                "operating_cash_flow": {"value": 260.0},
                "total_equity": {"value": 1800.0},
                "total_assets": {"value": 4000.0},
            },
            "extension_type": "RealEstate",
            "extension": {
                "ffo": {"value": 310.0},
            },
        }
    ]

    projections = project_selection_reports(reports_raw)

    assert len(projections) == 1
    report = projections[0]
    assert report.sic_code == 6798
    assert report.total_revenue == 1200.0
    assert report.net_income == 200.0
    assert report.operating_cash_flow == 260.0
    assert report.total_equity == 1800.0
    assert report.total_assets == 4000.0
    assert report.extension_ffo == 310.0


def test_select_valuation_model_uses_typed_projection() -> None:
    profile = CompanyProfile(
        ticker="REIT",
        name="Real Estate Trust",
        sector="Real Estate",
        industry="REIT",
        is_profitable=True,
    )
    reports_raw = [
        {
            "base": {
                "sic_code": {"value": "6798"},
                "total_revenue": {"value": 1200.0},
                "net_income": {"value": 200.0},
                "operating_cash_flow": {"value": 260.0},
                "total_equity": {"value": 1800.0},
                "total_assets": {"value": 4000.0},
            },
            "extension_type": "RealEstate",
            "extension": {
                "ffo": {"value": 310.0},
            },
        }
    ]
    projections = project_selection_reports(reports_raw)

    result = select_valuation_model(profile, projections)

    assert result.model == ValuationModel.FFO
    assert result.signals.data_coverage["extension_ffo"] is True
