from __future__ import annotations

from typing import Any

import pytest

from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.extractor import (
    SearchConfig,
)
from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.factory import (
    BaseFinancialModelFactory,
    FinancialReportFactory,
)
from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.mapping import (
    get_mapping_registry,
)
from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.report_contracts import (
    BaseFinancialModel,
    FinancialServicesExtension,
    IndustrialExtension,
    RealEstateExtension,
)
from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)


def _fake_extract(
    _extractor,
    _configs,
    name: str,
    target_type=float,
) -> TraceableField:
    value = 1.0 if target_type is float else "ok"
    return TraceableField(
        name=name,
        value=value,
        provenance=ManualProvenance(description="test"),
    )


def test_industrial_extension_uses_industrial_registry_and_exposes_components(
    monkeypatch,
) -> None:
    seen: list[tuple[str | None, str | None]] = []

    class DummyExtractor:
        ticker = "ABC"

    def fake_resolve(
        _field_key: str, *, industry: str | None = None, issuer: str | None = None
    ):
        seen.append((industry, issuer))
        return None

    monkeypatch.setattr(get_mapping_registry(), "resolve", fake_resolve)
    monkeypatch.setattr(
        BaseFinancialModelFactory, "_extract_field", staticmethod(_fake_extract)
    )

    extension = FinancialReportFactory._create_industrial_extension(DummyExtractor())

    assert seen
    assert all(industry == "Industrial" for industry, _issuer in seen)
    assert all(issuer == "ABC" for _industry, issuer in seen)
    assert extension.selling_expense.name == "Selling Expense"
    assert extension.ga_expense.name == "G&A Expense"


def test_financial_services_extension_uses_financial_registry(monkeypatch) -> None:
    seen: list[tuple[str | None, str | None]] = []

    class DummyExtractor:
        ticker = "JPM"

    def fake_resolve(
        _field_key: str, *, industry: str | None = None, issuer: str | None = None
    ):
        seen.append((industry, issuer))
        return None

    monkeypatch.setattr(get_mapping_registry(), "resolve", fake_resolve)
    monkeypatch.setattr(
        BaseFinancialModelFactory, "_extract_field", staticmethod(_fake_extract)
    )

    extension = FinancialReportFactory._create_financial_services_extension(
        DummyExtractor()
    )

    assert seen
    assert all(industry == "Financial Services" for industry, _issuer in seen)
    assert all(issuer == "JPM" for _industry, issuer in seen)
    assert extension.loans_and_leases.value == 1.0


def test_financial_services_tier1_fallback_supports_number_unit(monkeypatch) -> None:
    captured_tier1_configs: list[SearchConfig] = []

    class DummyExtractor:
        ticker = "JPM"

    def fake_resolve(
        _field_key: str, *, industry: str | None = None, issuer: str | None = None
    ):
        return None

    def capture_extract(
        _extractor,
        configs,
        name: str,
        target_type=float,
    ) -> TraceableField:
        if name == "Tier 1 Capital Ratio":
            captured_tier1_configs.extend(configs)
        value = 1.0 if target_type is float else "ok"
        return TraceableField(
            name=name,
            value=value,
            provenance=ManualProvenance(description="test"),
        )

    monkeypatch.setattr(get_mapping_registry(), "resolve", fake_resolve)
    monkeypatch.setattr(
        BaseFinancialModelFactory, "_extract_field", staticmethod(capture_extract)
    )

    FinancialReportFactory._create_financial_services_extension(DummyExtractor())

    assert captured_tier1_configs
    concepts = [cfg.concept_regex for cfg in captured_tier1_configs]
    assert "us-gaap:TierOneRiskBasedCapitalToRiskWeightedAssets" in concepts
    assert any(
        cfg.unit_whitelist is not None and "number" in cfg.unit_whitelist
        for cfg in captured_tier1_configs
    )


def test_real_estate_extension_exposes_gain_on_sale(monkeypatch) -> None:
    class DummyExtractor:
        ticker = "O"

    monkeypatch.setattr(
        BaseFinancialModelFactory, "_extract_field", staticmethod(_fake_extract)
    )
    base_model = BaseFinancialModel()

    extension = FinancialReportFactory._create_real_estate_extension(
        DummyExtractor(), base_model
    )

    assert extension.gain_on_sale.name == "Gain on Sale of Properties"


def test_base_model_create_uses_passed_industry_for_registry(monkeypatch) -> None:
    seen: list[tuple[str | None, str | None]] = []

    class DummyExtractor:
        ticker = "DUMMY"

        @staticmethod
        def search(_config):
            return []

        @staticmethod
        def sic_code():
            return "6798"

    def fake_resolve(
        _field_key: str, *, industry: str | None = None, issuer: str | None = None
    ):
        seen.append((industry, issuer))
        return None

    monkeypatch.setattr(get_mapping_registry(), "resolve", fake_resolve)
    monkeypatch.setattr(
        BaseFinancialModelFactory, "_extract_field", staticmethod(_fake_extract)
    )

    BaseFinancialModelFactory.create(DummyExtractor(), industry_type="Real Estate")

    assert seen
    assert all(industry == "Real Estate" for industry, _issuer in seen)
    assert all(issuer == "DUMMY" for _industry, issuer in seen)


@pytest.mark.parametrize(
    ("resolved_industry", "expected_extension_type", "expected_extension_cls"),
    [
        ("Industrial", "Industrial", IndustrialExtension),
        ("General", "Industrial", IndustrialExtension),
        ("Financial Services", "FinancialServices", FinancialServicesExtension),
        ("Real Estate", "RealEstate", RealEstateExtension),
    ],
)
def test_create_report_sets_canonical_extension_type(
    monkeypatch,
    resolved_industry: str,
    expected_extension_type: str,
    expected_extension_cls: type[Any],
) -> None:
    class DummyExtractor:
        def __init__(self, ticker: str, fiscal_year: int | None) -> None:
            self.ticker = ticker
            self.fiscal_year = fiscal_year

        @staticmethod
        def sic_code() -> str:
            return "0000"

        @staticmethod
        def get_selected_filing_metadata() -> dict[str, object]:
            return {
                "form": "10-K",
                "selection_mode": "fiscal_year_match",
                "matched_fiscal_year": 2025,
            }

    monkeypatch.setattr(
        "src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.factory.SECReportExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        BaseFinancialModelFactory,
        "create",
        staticmethod(
            lambda _extractor, _industry_type=None: BaseFinancialModel(
                fiscal_year=TraceableField(
                    name="Fiscal Year",
                    value="2025",
                    provenance=ManualProvenance(description="test"),
                )
            )
        ),
    )
    monkeypatch.setattr(
        FinancialReportFactory,
        "_resolve_industry_type",
        staticmethod(lambda _sic_code: resolved_industry),
    )
    monkeypatch.setattr(
        FinancialReportFactory,
        "_create_industrial_extension",
        staticmethod(lambda _extractor: IndustrialExtension()),
    )
    monkeypatch.setattr(
        FinancialReportFactory,
        "_create_financial_services_extension",
        staticmethod(lambda _extractor: FinancialServicesExtension()),
    )
    monkeypatch.setattr(
        FinancialReportFactory,
        "_create_real_estate_extension",
        staticmethod(lambda _extractor, _base_model: RealEstateExtension()),
    )

    report = FinancialReportFactory.create_report("DUMMY", 2025)

    assert report.industry_type == expected_extension_type
    assert report.extension_type == expected_extension_type
    assert isinstance(report.extension, expected_extension_cls)
    assert isinstance(report.filing_metadata, dict)
    assert report.filing_metadata.get("form") == "10-K"
    assert report.filing_metadata.get("matched_fiscal_year") == 2025
