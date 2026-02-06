from unittest.mock import MagicMock

import pytest

from src.workflow.nodes.fundamental_analysis.factories import (
    FinancialReportFactory,
)
from src.workflow.nodes.fundamental_analysis.financial_models import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)
from src.workflow.nodes.fundamental_analysis.tools.sec_extractor import (
    SECExtractResult,
    SECReportExtractor,
)


# Mock SECExtractResult
def create_mock_result(concept, value, period_key="2023"):
    return SECExtractResult(
        concept=concept,
        value=str(value) if value is not None else None,
        label="Test Label",
        statement="Test Statement",
        period_key=period_key,
        dimensions=None,
        dimension_detail={},
    )


@pytest.fixture
def mock_extractor():
    extractor = MagicMock(spec=SECReportExtractor)
    extractor.ticker = "TEST"
    extractor.sic_code.return_value = "1234"
    return extractor


def test_industrial_extension_inventory_fallback(mock_extractor):
    # Setup: InventoryNet is missing, InventoryGross is present
    def search_side_effect(config):
        if "InventoryNet" in config.concept_regex:
            return []
        if "InventoryGross" in config.concept_regex:
            return [create_mock_result("us-gaap:InventoryGross", 100.0)]
        return []

    mock_extractor.search.side_effect = search_side_effect

    # Test _create_industrial_extension directly?
    # Or test via create_report logic if we can control SIC.

    extension = FinancialReportFactory._create_industrial_extension(mock_extractor)

    assert extension.inventory.value == 100.0
    assert isinstance(extension.inventory.provenance, XBRLProvenance)
    assert extension.inventory.provenance.concept == "us-gaap:InventoryGross"


def test_industrial_extension_sga_calculation(mock_extractor):
    # Setup: Aggregate SG&A is missing. Selling and G&A are present.
    def search_side_effect(config):
        if "SellingGeneralAndAdministrativeExpense" in config.concept_regex:
            return []
        if "SellingExpense" in config.concept_regex:
            return [create_mock_result("us-gaap:SellingExpense", 50.0)]
        if "GeneralAndAdministrativeExpense" in config.concept_regex:
            return [create_mock_result("us-gaap:GeneralAndAdministrativeExpense", 30.0)]
        return []

    mock_extractor.search.side_effect = search_side_effect

    extension = FinancialReportFactory._create_industrial_extension(mock_extractor)

    assert extension.sga_expense.value == 80.0
    assert isinstance(extension.sga_expense.provenance, ComputedProvenance)
    assert extension.sga_expense.provenance.op_code == "SUM"
    assert "Selling Expense" in extension.sga_expense.provenance.inputs
    assert "G&A Expense" in extension.sga_expense.provenance.inputs


def test_real_estate_ffo_calculation(mock_extractor):
    # Setup base model
    base_model = MagicMock()
    # Create a real TraceableField for net_income to satisfy Pydantic validation
    base_model.net_income = TraceableField(
        name="Net Income", value=1000.0, provenance=ManualProvenance(description="Mock")
    )

    # Setup extractor for Depreciation and GainOnSale
    def search_side_effect(config):
        if "DepreciationAndAmortizationInRealEstate" in config.concept_regex:
            return [
                create_mock_result(
                    "us-gaap:DepreciationAndAmortizationInRealEstate", 200.0
                )
            ]
        if "GainLossOnSaleOfRealEstateInvestmentProperty" in config.concept_regex:
            return [
                create_mock_result(
                    "us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty", 50.0
                )
            ]
        return []

    mock_extractor.search.side_effect = search_side_effect

    extension = FinancialReportFactory._create_real_estate_extension(
        mock_extractor, base_model
    )

    # FFO = Net Income (1000) + Depreciation (200) - GainOnSale (50) = 1150
    assert extension.ffo.value == 1150.0
    assert isinstance(extension.ffo.provenance, ComputedProvenance)
    assert extension.ffo.provenance.op_code == "FFO_CALC"
