from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from src.agents.fundamental.data.clients.sec_xbrl.forward_signals_text import (
    FilingTextRecord,
    _extract_focus_text_from_filing,
    extract_forward_signals_from_sec_text,
)
from src.agents.fundamental.data.clients.sec_xbrl.utils import fetch_financial_payload


def test_extract_forward_signals_from_sec_text_emits_structured_signals() -> None:
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            text=(
                "Management raised guidance and expects higher revenue in 2026. "
                "The business also sees margin expansion from operating leverage."
            ),
        ),
        FilingTextRecord(
            form="8-K",
            source_type="press_release",
            period="Q4 2025",
            text=(
                "The company warned of margin pressure from cost inflation and "
                "reported soft demand with lowered guidance."
            ),
        ),
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )

    assert signals
    mda_growth = next(
        (
            item
            for item in signals
            if item.get("source_type") == "mda"
            and item.get("metric") == "growth_outlook"
        ),
        None,
    )
    press_margin = next(
        (
            item
            for item in signals
            if item.get("source_type") == "press_release"
            and item.get("metric") == "margin_outlook"
        ),
        None,
    )
    assert mda_growth is not None
    assert mda_growth["direction"] == "up"
    assert mda_growth["unit"] == "basis_points"
    assert isinstance(mda_growth["evidence"], list)
    assert mda_growth["evidence"][0]["source_url"].startswith(
        "https://www.sec.gov/edgar/search/"
    )
    assert press_margin is not None
    assert press_margin["direction"] == "down"


def test_extract_forward_signals_from_sec_text_returns_empty_without_patterns() -> None:
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            text="This filing discusses general operations without outlook language.",
        )
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )
    assert signals == []


def test_extract_forward_signals_from_sec_text_prefers_mda_section_for_10k() -> None:
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            text=(
                "Item 1A. Risk Factors. The company cited lowered guidance and "
                "margin pressure from inflation. "
                "Item 7. Management's Discussion and Analysis of Financial Condition "
                "and Results of Operations. Management raised guidance and expects "
                "higher revenue with margin expansion from operating leverage. "
                "Item 7A. Quantitative and Qualitative Disclosures About Market Risk."
            ),
        )
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )

    growth_signal = next(
        (
            item
            for item in signals
            if item.get("source_type") == "mda"
            and item.get("metric") == "growth_outlook"
        ),
        None,
    )
    assert growth_signal is not None
    assert growth_signal["direction"] == "up"
    evidence = growth_signal.get("evidence")
    assert isinstance(evidence, list) and evidence
    assert evidence[0]["doc_type"] == "10-K_focused"


def test_fetch_financial_payload_combines_xbrl_and_sec_text_signals() -> None:
    with (
        patch(
            "src.agents.fundamental.data.clients.sec_xbrl.utils.fetch_financial_data",
            return_value=[],
        ),
        patch(
            "src.agents.fundamental.data.clients.sec_xbrl.utils.extract_forward_signals_from_xbrl_reports",
            return_value=[
                {
                    "signal_id": "xbrl-growth",
                    "source_type": "manual",
                    "metric": "growth_outlook",
                    "direction": "up",
                    "value": 80.0,
                    "unit": "basis_points",
                    "confidence": 0.61,
                    "evidence": [{"text_snippet": "xbrl", "source_url": "https://sec"}],
                }
            ],
        ),
        patch(
            "src.agents.fundamental.data.clients.sec_xbrl.utils.extract_forward_signals_from_sec_text",
            return_value=[
                {
                    "signal_id": "text-margin",
                    "source_type": "mda",
                    "metric": "margin_outlook",
                    "direction": "down",
                    "value": 60.0,
                    "unit": "basis_points",
                    "confidence": 0.59,
                    "evidence": [{"text_snippet": "text", "source_url": "https://sec"}],
                }
            ],
        ),
    ):
        payload = fetch_financial_payload("AAPL", years=3)

    assert payload["financial_reports"] == []
    assert isinstance(payload["forward_signals"], list)
    signal_ids = [item.get("signal_id") for item in payload["forward_signals"]]
    assert "xbrl-growth" in signal_ids
    assert "text-margin" in signal_ids


def test_extract_forward_signals_from_sec_text_logs_focus_diagnostics() -> None:
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            text=(
                "Item 7. Management's Discussion and Analysis of Financial Condition "
                "and Results of Operations. Management raised guidance and expects "
                "higher revenue with margin expansion from operating leverage. "
                "Item 7A. Quantitative and Qualitative Disclosures About Market Risk."
            ),
            focus_text=(
                "Management's Discussion and Analysis. Management raised guidance and "
                "expects higher revenue with margin expansion."
            ),
        )
    ]

    with patch(
        "src.agents.fundamental.data.clients.sec_xbrl.forward_signals_text.log_event"
    ) as mock_log:
        signals = extract_forward_signals_from_sec_text(
            ticker="AAPL",
            fetch_records_fn=lambda _ticker, _limit: records,
        )

    assert signals
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_forward_signal_text_producer_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["records_total"] == 1
    assert fields["focused_records_total"] == 1
    assert fields["fallback_records_total"] == 0
    assert fields["focused_form_counts"] == {"10-K": 1}
    assert "10-K_focused" in fields["emitted_doc_types"]
    assert fields["focused_signals_count"] >= 1
    assert fields["emitted_focused_doc_types"] == ["10-K_focused"]
    assert fields["pipeline_records_processed"] == 1
    assert fields["pipeline_metric_queries_total"] == 2
    assert fields["pipeline_analysis_sentences_total"] >= 1
    assert fields["pipeline_retrieval_sentences_by_metric"]["growth_outlook"] >= 0
    assert fields["pipeline_split_ms_total"] >= 0.0
    assert fields["pipeline_fls_ms_total"] >= 0.0
    assert fields["pipeline_fls_model_load_ms_total"] >= 0.0
    assert fields["pipeline_fls_inference_ms_total"] >= 0.0
    assert fields["pipeline_fls_sentences_scored_total"] >= 0
    assert fields["pipeline_fls_prefilter_selected_total"] >= 0
    assert fields["pipeline_fls_batches_total"] >= 0
    assert fields["pipeline_fls_cache_hits_total"] >= 0
    assert fields["pipeline_fls_cache_misses_total"] >= 0
    assert fields["pipeline_fls_fast_skip_records_total"] >= 0
    assert fields["pipeline_fls_fast_skip_sentences_total"] >= 0
    assert fields["pipeline_fls_fast_skip_ratio"] >= 0.0
    assert fields["pipeline_retrieval_ms_total"] >= 0.0
    assert fields["pipeline_pattern_ms_total"] >= 0.0


def test_extract_forward_signals_from_sec_text_fast_skips_fls_without_cues() -> None:
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            text=(
                "This section describes historical accounting treatments and "
                "prior-period operating structure updates for fiscal year 2024."
            ),
        )
    ]

    with (
        patch(
            "src.agents.fundamental.data.clients.sec_xbrl.forward_signals_text.filter_forward_looking_sentences_with_stats",
            side_effect=AssertionError(
                "FLS should be skipped when no cues are present"
            ),
        ),
        patch(
            "src.agents.fundamental.data.clients.sec_xbrl.forward_signals_text.log_event"
        ) as mock_log,
    ):
        signals = extract_forward_signals_from_sec_text(
            ticker="AAPL",
            fetch_records_fn=lambda _ticker, _limit: records,
        )

    assert signals == []
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_forward_signal_text_producer_no_signal"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["pipeline_records_processed"] == 1
    assert fields["pipeline_fls_fast_skip_records_total"] == 1
    assert fields["pipeline_fls_fast_skip_sentences_total"] >= 1
    assert fields["pipeline_fls_fast_skip_ratio"] == 1.0
    assert fields["pipeline_fls_ms_total"] == 0.0


def test_extract_forward_signals_from_sec_text_handles_negation_and_numeric_guidance() -> (
    None
):
    records = [
        FilingTextRecord(
            form="10-Q",
            source_type="mda",
            period="Q4 2025",
            text=(
                "Management did not raise guidance in the prior year discussion. "
                "Management expects higher revenue and raised guidance by 5% for 2026."
            ),
        )
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )

    growth_signal = next(
        (
            item
            for item in signals
            if item.get("source_type") == "mda"
            and item.get("metric") == "growth_outlook"
        ),
        None,
    )
    assert growth_signal is not None
    assert growth_signal["direction"] == "up"
    evidence = growth_signal.get("evidence")
    assert isinstance(evidence, list)
    assert any(
        isinstance(item, dict) and item.get("rule") == "numeric_guidance"
        for item in evidence
    )
    assert growth_signal["confidence"] > 0.60


def test_extract_forward_signals_from_sec_text_enriches_evidence_provenance() -> None:
    records = [
        FilingTextRecord(
            form="10-Q",
            source_type="mda",
            period="Q4 2025",
            filing_date="2025-11-03",
            accession_number="0000320193-25-000073",
            cik="0000320193",
            focus_strategy="edgartools_part_item",
            text=(
                "Management expects higher revenue and raised guidance by 4% for 2026."
            ),
        )
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )
    assert signals
    evidence = signals[0]["evidence"][0]
    assert evidence["filing_date"] == "2025-11-03"
    assert evidence["accession_number"] == "0000320193-25-000073"
    assert (
        evidence["source_url"] == "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000073/0000320193-25-000073-index.html"
    )
    assert evidence["focus_strategy"] == "edgartools_part_item"
    assert evidence["rule"] in {"lexical_pattern", "numeric_guidance"}


def test_extract_forward_signals_from_sec_text_applies_staleness_penalty() -> None:
    fresh_date = date.today().isoformat()
    stale_date = (date.today() - timedelta(days=1200)).isoformat()
    base_text = "Management expects higher revenue and raised guidance."

    fresh_signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: [
            FilingTextRecord(
                form="10-K",
                source_type="mda",
                filing_date=fresh_date,
                text=base_text,
            )
        ],
    )
    stale_signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: [
            FilingTextRecord(
                form="10-K",
                source_type="mda",
                filing_date=stale_date,
                text=base_text,
            )
        ],
    )
    assert fresh_signals and stale_signals
    assert stale_signals[0]["confidence"] < fresh_signals[0]["confidence"]
    assert stale_signals[0]["median_filing_age_days"] > 900


def test_extract_focus_text_from_filing_prefers_part_aware_item_for_10q() -> None:
    class FakeTenQ:
        def get_item_with_part(self, part: str, item: str) -> str:
            if part == "Part I" and item == "Item 2":
                return (
                    "Management's Discussion and Analysis expects higher revenue and "
                    "margin expansion through operating leverage."
                )
            return ""

    class FakeFiling:
        def obj(self) -> FakeTenQ:
            return FakeTenQ()

    focus_text = _extract_focus_text_from_filing(form="10-Q", filing=FakeFiling())
    assert isinstance(focus_text, str)
    assert "expects higher revenue" in focus_text
