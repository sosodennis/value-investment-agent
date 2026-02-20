from __future__ import annotations

import pandas as pd

from src.agents.fundamental.data.clients.sec_xbrl.extractor import (
    SearchType,
    SECExtractResult,
    SECReportExtractor,
)
from src.agents.fundamental.data.clients.sec_xbrl.factory import (
    BaseFinancialModelFactory,
)
from src.agents.fundamental.data.clients.sec_xbrl.resolver import (
    ParsedCandidate,
    choose_best_candidate,
    rank_results,
)


def _result(period_key: str, concept: str = "us-gaap:DebtCurrent") -> SECExtractResult:
    return SECExtractResult(
        concept=concept,
        value="100",
        label=None,
        statement="balance sheet",
        period_key=period_key,
        dimensions="None (Total)",
        dimension_detail={},
        unit="USD",
        decimals=None,
        scale=None,
    )


def test_rank_results_prefers_latest_period() -> None:
    config = SearchType.CONSOLIDATED("us-gaap:DebtCurrent")
    ranked = rank_results(
        [
            _result("instant_2024-12-31"),
            _result("instant_2025-12-31"),
        ],
        config,
    )
    assert ranked[0].result.period_key == "instant_2025-12-31"


def test_choose_best_candidate_prefers_mapping_priority() -> None:
    config = SearchType.CONSOLIDATED("us-gaap:DebtCurrent")
    ranked = rank_results(
        [
            _result("instant_2024-12-31"),
            _result("instant_2025-12-31"),
        ],
        config,
    )

    # config_index 0 represents higher priority mapping than config_index 1.
    candidates = [
        ParsedCandidate(config_index=0, ranked=ranked[1], value=100.0),
        ParsedCandidate(config_index=1, ranked=ranked[0], value=200.0),
    ]
    selected = choose_best_candidate(candidates)
    assert selected is not None
    assert selected.config_index == 0
    assert selected.value == 100.0


def test_search_dedup_keeps_different_period_rows() -> None:
    extractor = SECReportExtractor.__new__(SECReportExtractor)
    extractor.ticker = "TEST"
    extractor.fiscal_year = 2025
    extractor.standard_industrial_classification_code = None
    extractor.actual_date = None
    extractor.real_dim_cols = []
    extractor.df = pd.DataFrame(
        [
            {
                "concept": "us-gaap:DebtCurrent",
                "value": "100",
                "period_key": "instant_2025-12-31",
                "period_end": "2025-12-31",
                "statement_type": "balance sheet",
                "unit": "USD",
            },
            {
                "concept": "us-gaap:DebtCurrent",
                "value": "100",
                "period_key": "instant_2024-12-31",
                "period_end": "2024-12-31",
                "statement_type": "balance sheet",
                "unit": "USD",
            },
        ]
    )

    config = SearchType.CONSOLIDATED(
        "us-gaap:DebtCurrent",
        statement_types=["balance"],
        period_type="instant",
        unit_whitelist=["usd"],
        respect_anchor_date=False,
    )

    results = extractor.search(config)
    assert len(results) == 2


def test_search_dedup_keeps_dimensional_and_consolidated_rows() -> None:
    extractor = SECReportExtractor.__new__(SECReportExtractor)
    extractor.ticker = "TEST"
    extractor.fiscal_year = 2025
    extractor.standard_industrial_classification_code = None
    extractor.actual_date = None
    extractor.real_dim_cols = ["dim_ProductAxis"]
    extractor.df = pd.DataFrame(
        [
            {
                "concept": "us-gaap:DebtCurrent",
                "value": "100",
                "period_key": "instant_2025-12-31",
                "period_end": "2025-12-31",
                "statement_type": "balance sheet",
                "unit": "USD",
                "dim_ProductAxis": None,
            },
            {
                "concept": "us-gaap:DebtCurrent",
                "value": "100",
                "period_key": "instant_2025-12-31",
                "period_end": "2025-12-31",
                "statement_type": "balance sheet",
                "unit": "USD",
                "dim_ProductAxis": "CustomMember",
            },
        ]
    )

    consolidated = SearchType.CONSOLIDATED(
        "us-gaap:DebtCurrent",
        statement_types=["balance"],
        period_type="instant",
        unit_whitelist=["usd"],
        respect_anchor_date=False,
    )
    dimensional = SearchType.DIMENSIONAL(
        "us-gaap:DebtCurrent",
        dimension_regex="CustomMember",
        statement_types=["balance"],
        period_type="instant",
        unit_whitelist=["usd"],
        respect_anchor_date=False,
    )

    consolidated_results = extractor.search(consolidated)
    dimensional_results = extractor.search(dimensional)
    assert len(consolidated_results) == 1
    assert len(dimensional_results) == 1


def test_extract_field_falls_back_to_strict_dimensional() -> None:
    class DummyExtractor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool, str | None]] = []

        def search(self, config):
            self.calls.append(
                (
                    config.type_name,
                    config.statement_types is None,
                    config.dimension_regex,
                )
            )
            if config.type_name == "DIMENSIONAL" and config.statement_types is not None:
                return [
                    SECExtractResult(
                        concept="custom:AssetsBySegment",
                        value="250",
                        label=None,
                        statement="balance sheet",
                        period_key="instant_2025-12-31",
                        dimensions="ProductAxis: Consumer",
                        dimension_detail={"ProductAxis": "Consumer"},
                        unit="USD",
                        decimals=None,
                        scale=None,
                    )
                ]
            return []

    extractor = DummyExtractor()
    field = BaseFinancialModelFactory._extract_field(
        extractor=extractor,
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Assets",
                statement_types=["balance"],
                period_type="instant",
                unit_whitelist=["usd"],
            )
        ],
        name="Total Assets",
        target_type=float,
    )

    assert field.value == 250.0
    assert any(call[0] == "CONSOLIDATED" for call in extractor.calls)
    assert any(
        call[0] == "DIMENSIONAL" and call[1] is False for call in extractor.calls
    )


def test_extract_field_falls_back_to_relaxed_context_stage() -> None:
    class DummyExtractor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool, bool]] = []

        def search(self, config):
            self.calls.append(
                (
                    config.type_name,
                    config.statement_types is None,
                    config.respect_anchor_date,
                )
            )
            if config.statement_types is None and config.respect_anchor_date is False:
                return [
                    SECExtractResult(
                        concept="us-gaap:Assets",
                        value="175",
                        label=None,
                        statement="statement of financial position",
                        period_key="instant_2025-12-31",
                        dimensions="None (Total)",
                        dimension_detail={},
                        unit="USD",
                        decimals=None,
                        scale=None,
                    )
                ]
            return []

    extractor = DummyExtractor()
    field = BaseFinancialModelFactory._extract_field(
        extractor=extractor,
        configs=[
            SearchType.CONSOLIDATED(
                "us-gaap:Assets",
                statement_types=["balance"],
                period_type="instant",
                unit_whitelist=["usd"],
                respect_anchor_date=True,
            )
        ],
        name="Total Assets",
        target_type=float,
    )

    assert field.value == 175.0
    assert any(
        call[0] == "CONSOLIDATED" and call[1] is False for call in extractor.calls
    )
    assert any(call[1] is True and call[2] is False for call in extractor.calls)
