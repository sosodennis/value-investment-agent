from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from src.agents.fundamental.infrastructure.sec_xbrl.finbert_direction import (
    FinbertDirectionReview,
)
from src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text import (
    _apply_finbert_direction_reviews,
    _extract_focus_text_from_filing,
    _normalize_text,
    extract_forward_signals_from_sec_text,
)
from src.agents.fundamental.infrastructure.sec_xbrl.matchers.regex_signal_extractor import (
    MetricRegexHits,
    PatternHit,
)
from src.agents.fundamental.infrastructure.sec_xbrl.pipeline_evidence_service import (
    _extract_snippet,
)
from src.agents.fundamental.infrastructure.sec_xbrl.provider import (
    fetch_financial_payload,
)
from src.agents.fundamental.infrastructure.sec_xbrl.text_record import FilingTextRecord


class _SyntheticFinancialReport(BaseModel):
    base: dict[str, object]
    industry_type: str
    extension_type: str | None = None
    extension: dict[str, object] | None = None


def _assert_aligned_to_token_boundaries(snippet: str, normalized_text: str) -> None:
    start = normalized_text.index(snippet)
    if start > 0:
        assert normalized_text[start - 1] == " "
    end = start + len(snippet)
    if end < len(normalized_text):
        assert normalized_text[end] == " "


def test_extract_snippet_aligns_to_word_boundaries() -> None:
    text = (
        "Our TAC rate will continue to be affected by changes in device mix; "
        "geographic mix; partner agreement terms; partner mix; the percentage "
        "of queries channeled through paid access points; product mix; the "
        "relative revenue growth rates of advertising revenues from different "
        "channels; and revenue sharing rates."
    )
    start = text.index("revenue growth rates")
    end = start + len("revenue growth rates")

    snippet = _extract_snippet(text, start, end, radius=40)

    assert snippet is not None
    normalized = " ".join(text.split())
    assert snippet in normalized
    _assert_aligned_to_token_boundaries(snippet, normalized)


def test_extract_snippet_prefers_sentence_boundaries() -> None:
    text = (
        "We continue to invest in infrastructure capacity. "
        "Revenue growth rates are expected to improve with stronger product mix. "
        "Operating leverage should also support margin expansion next year."
    )
    start = text.index("Revenue growth rates")
    end = start + len("Revenue growth rates")

    snippet = _extract_snippet(text, start, end, radius=20)

    assert snippet is not None
    normalized = " ".join(text.split())
    assert snippet in normalized
    assert (
        "Revenue growth rates are expected to improve with stronger product mix."
        in snippet
    )
    assert snippet[0].isupper()
    assert snippet[-1] in ".!?"


def test_extract_snippet_truncates_on_word_boundary() -> None:
    text = " ".join(f"token{i}" for i in range(700))
    start = text.index("token320")
    end = start + len("token320")

    snippet = _extract_snippet(text, start, end, radius=1_100)

    assert snippet is not None
    assert len(snippet) <= 1_200
    normalized = " ".join(text.split())
    assert snippet in normalized
    _assert_aligned_to_token_boundaries(snippet, normalized)


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


def test_extract_forward_signals_from_sec_text_captures_margin_downward_pressure() -> (
    None
):
    records = [
        FilingTextRecord(
            form="10-Q",
            source_type="mda",
            period="Q1 2026",
            text=(
                "As a result, the company believes gross margins will be subject to "
                "volatility and downward pressure in the coming quarters."
            ),
        )
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )

    margin_signal = next(
        (
            item
            for item in signals
            if item.get("metric") == "margin_outlook"
            and item.get("direction") == "down"
        ),
        None,
    )
    assert margin_signal is not None
    assert margin_signal["source_type"] == "mda"


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
            "src.agents.fundamental.infrastructure.sec_xbrl.financial_payload_service.fetch_financial_data",
            return_value=[],
        ),
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.financial_payload_service.extract_forward_signals_from_xbrl_reports",
            return_value=[
                {
                    "signal_id": "xbrl-growth",
                    "source_type": "xbrl_auto",
                    "metric": "growth_outlook",
                    "direction": "up",
                    "value": 80.0,
                    "unit": "basis_points",
                    "confidence": 0.61,
                    "evidence": [
                        {
                            "preview_text": "xbrl",
                            "full_text": "xbrl",
                            "source_url": "https://sec",
                        }
                    ],
                }
            ],
        ),
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.financial_payload_service.extract_forward_signals_from_sec_text",
            return_value=[
                {
                    "signal_id": "text-margin",
                    "source_type": "mda",
                    "metric": "margin_outlook",
                    "direction": "down",
                    "value": 60.0,
                    "unit": "basis_points",
                    "confidence": 0.59,
                    "evidence": [
                        {
                            "preview_text": "text",
                            "full_text": "text",
                            "source_url": "https://sec",
                        }
                    ],
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


def test_fetch_financial_payload_normalizes_reports_to_canonical_json() -> None:
    report_model = _SyntheticFinancialReport(
        base={
            "fiscal_year": {"value": "2025"},
            "total_revenue": {"value": 1000.0},
            "net_income": {"value": 100.0},
            "operating_cash_flow": {"value": 120.0},
            "total_equity": {"value": 700.0},
            "total_assets": {"value": 1500.0},
        },
        industry_type="Industrial",
        extension_type="Industrial",
        extension={"capex": {"value": 50.0}},
    )

    with patch(
        "src.agents.fundamental.infrastructure.sec_xbrl.provider._fetch_financial_payload",
        return_value={
            "financial_reports": [report_model],
            "forward_signals": [{"signal_id": "sig-1"}],
        },
    ):
        payload = fetch_financial_payload("AAPL", years=3)

    reports = payload["financial_reports"]
    assert isinstance(reports, list)
    assert len(reports) == 1
    first = reports[0]
    assert isinstance(first, dict)
    assert first["industry_type"] == "Industrial"
    assert first["extension_type"] == "Industrial"
    assert isinstance(first.get("base"), dict)
    assert payload["forward_signals"] == [{"signal_id": "sig-1"}]


def test_fetch_financial_payload_rejects_extension_without_extension_type() -> None:
    report_model = _SyntheticFinancialReport(
        base={"fiscal_year": {"value": "2025"}},
        industry_type="Industrial",
        extension={"capex": {"value": 50.0}},
    )

    with patch(
        "src.agents.fundamental.infrastructure.sec_xbrl.provider._fetch_financial_payload",
        return_value={
            "financial_reports": [report_model],
            "forward_signals": [],
        },
    ):
        with pytest.raises(TypeError, match="extension requires extension_type"):
            fetch_financial_payload("AAPL", years=3)


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
        "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.log_event"
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
    assert fields["pipeline_8k_sections_selected_total"] >= 0
    assert fields["pipeline_8k_noise_paragraphs_skipped_total"] >= 0
    assert fields["pipeline_split_ms_total"] >= 0.0
    assert fields["pipeline_fls_ms_total"] >= 0.0
    assert fields["pipeline_pattern_lemma_hits_total"] >= 0
    assert fields["pipeline_pattern_dependency_hits_total"] >= 0
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
    assert fields["pipeline_finbert_direction_review_candidates_total"] >= 0
    assert fields["pipeline_finbert_direction_reviewed_total"] >= 0
    assert fields["pipeline_finbert_direction_accepted_total"] >= 0
    assert fields["pipeline_finbert_direction_overrides_total"] >= 0
    assert fields["pipeline_finbert_direction_ms_total"] >= 0.0
    assert fields["pipeline_finbert_direction_avg_ms"] >= 0.0


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
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.filter_forward_looking_sentences_with_stats",
            side_effect=AssertionError(
                "FLS should be skipped when no cues are present"
            ),
        ),
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.log_event"
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


def test_extract_forward_signals_from_sec_text_matches_lemma_variants() -> None:
    records = [
        FilingTextRecord(
            form="10-Q",
            source_type="mda",
            period="Q4 2025",
            text=(
                "Management is expecting sales to accelerate next year. "
                "Management expects margins to improve with operating leverage."
            ),
        )
    ]

    signals = extract_forward_signals_from_sec_text(
        ticker="AAPL",
        fetch_records_fn=lambda _ticker, _limit: records,
    )
    assert signals

    growth_signal = next(
        (
            item
            for item in signals
            if item.get("source_type") == "mda"
            and item.get("metric") == "growth_outlook"
        ),
        None,
    )
    margin_signal = next(
        (
            item
            for item in signals
            if item.get("source_type") == "mda"
            and item.get("metric") == "margin_outlook"
        ),
        None,
    )
    assert growth_signal is not None
    assert margin_signal is not None
    assert growth_signal["direction"] == "up"
    assert margin_signal["direction"] == "up"
    assert any(
        isinstance(item, dict) and item.get("rule") == "lemma_pattern"
        for item in growth_signal.get("evidence", [])
    )


def test_extract_forward_signals_from_sec_text_tracks_8k_section_diagnostics() -> None:
    records = [
        FilingTextRecord(
            form="8-K",
            source_type="press_release",
            period="Q4 2025",
            text=(
                "FORM 8-K. Item 8.01 Other Events. Management raised guidance and "
                "expects higher revenue for 2026. "
                "SIGNATURES Pursuant to the requirements of the Securities Exchange Act, "
                "the registrant has duly caused this report to be signed."
            ),
        )
    ]

    with patch(
        "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.log_event"
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
    assert fields["pipeline_8k_sections_selected_total"] >= 1
    assert fields["pipeline_8k_noise_paragraphs_skipped_total"] >= 1


def test_extract_forward_signals_from_sec_text_accepts_dependency_hits() -> None:
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            text="General discussion without direct phrase guidance.",
        )
    ]

    def _dependency_stub(
        *, text: str, metric: str
    ) -> tuple[list[PatternHit], list[PatternHit]]:
        if metric != "growth_outlook":
            return [], []
        return (
            [
                PatternHit(
                    pattern="dependency_growth_outlook_up",
                    start=0,
                    end=min(len(text), 25),
                    weighted_score=1.15,
                    is_forward=True,
                    is_historical=False,
                    rule="dependency_pattern",
                )
            ],
            [],
        )

    with (
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.find_metric_dependency_hits",
            side_effect=_dependency_stub,
        ),
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.log_event"
        ) as mock_log,
    ):
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
    assert any(
        isinstance(item, dict) and item.get("rule") == "dependency_pattern"
        for item in growth_signal.get("evidence", [])
    )
    completion_call = next(
        call
        for call in mock_log.call_args_list
        if call.kwargs["event"] == "fundamental_forward_signal_text_producer_completed"
    )
    fields = completion_call.kwargs["fields"]
    assert fields["pipeline_pattern_dependency_hits_total"] >= 1
    assert fields["pipeline_pattern_dependency_hits_by_metric"]["growth_outlook"] >= 1


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
    assert evidence["rule"] in {
        "lexical_pattern",
        "lemma_pattern",
        "dependency_pattern",
        "numeric_guidance",
    }


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


def test_extract_forward_signals_from_sec_text_deduplicates_similar_evidence() -> None:
    text = "Management expects higher revenue and raised guidance for next fiscal year."
    start = text.index("expects")
    end = start + len("expects higher revenue")
    hit_primary = PatternHit(
        pattern="expects higher revenue",
        start=start,
        end=end,
        weighted_score=1.2,
        is_forward=True,
        is_historical=False,
        rule="dependency_pattern",
    )
    hit_shifted = PatternHit(
        pattern="higher revenue and raised",
        start=start + 2,
        end=end + 2,
        weighted_score=1.2,
        is_forward=True,
        is_historical=False,
        rule="dependency_pattern",
    )
    records = [
        FilingTextRecord(
            form="10-K",
            source_type="mda",
            period="FY2025",
            filing_date="2025-11-03",
            accession_number="0000320193-25-000073",
            cik="0000320193",
            text=text,
        )
    ]
    with (
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.extract_metric_regex_hits",
            return_value=MetricRegexHits(
                up_hits=[hit_primary, hit_shifted],
                down_hits=[],
                numeric_hits=[],
            ),
        ),
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.find_metric_lemma_hits",
            return_value=([], []),
        ),
        patch(
            "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.find_metric_dependency_hits",
            return_value=([], []),
        ),
    ):
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
    evidence = growth_signal["evidence"]
    assert isinstance(evidence, list)
    assert len(evidence) == 1


def test_apply_finbert_direction_reviews_overrides_signal_direction() -> None:
    signals = [
        {
            "signal_id": "s1",
            "source_type": "mda",
            "metric": "growth_outlook",
            "direction": "up",
            "value": 80.0,
            "unit": "basis_points",
            "confidence": 0.62,
            "evidence": [
                {
                    "preview_text": "preview",
                    "full_text": "Management expects demand softness next quarter.",
                    "source_url": "https://sec",
                }
            ],
        }
    ]

    with patch(
        "src.agents.fundamental.infrastructure.sec_xbrl.forward_signals_text.review_signal_direction_with_finbert",
        return_value=FinbertDirectionReview(
            elapsed_ms=12.0,
            reviewed=True,
            accepted=True,
            direction="down",
            confidence=0.91,
            label="negative",
            reason="accepted_override_direction",
        ),
    ):
        fields = _apply_finbert_direction_reviews(signals)

    assert signals[0]["direction"] == "down"
    assert signals[0]["confidence"] > 0.62
    assert fields["pipeline_finbert_direction_overrides_total"] == 1
    assert fields["pipeline_finbert_direction_ms_total"] == 12.0
    assert (
        fields["pipeline_finbert_direction_reasons"]["accepted_override_direction"] == 1
    )


def test_normalize_text_converts_date_and_datetime_values() -> None:
    assert _normalize_text(date(2025, 11, 3)) == "2025-11-03"
    assert _normalize_text(datetime(2025, 11, 3, 14, 35, 0)) == "2025-11-03"


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
