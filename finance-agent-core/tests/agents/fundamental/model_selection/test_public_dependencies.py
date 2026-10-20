from src.agents.fundamental.subdomains.core_valuation.public import ValuationModel
from src.agents.fundamental.subdomains.model_selection.domain.model_selection import (
    select_valuation_model,
)
from src.agents.fundamental.subdomains.model_selection.interface.report_projection_service import (
    project_selection_reports,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile


def test_model_selection_uses_public_capability_contracts() -> None:
    reports = project_selection_reports(
        [
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
                "extension": {"ffo": {"value": 310.0}},
            }
        ]
    )

    assert reports[0].extension_ffo == 310.0
    result = select_valuation_model(
        CompanyProfile(
            ticker="REIT",
            name="Real Estate Trust",
            sector="Real Estate",
            industry="REIT",
            is_profitable=True,
        ),
        reports,
    )

    assert result.model is ValuationModel.FFO
    assert result.signals.data_coverage["extension_ffo"] is True
