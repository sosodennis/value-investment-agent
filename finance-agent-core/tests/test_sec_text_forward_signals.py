from __future__ import annotations

from unittest.mock import patch

from src.agents.fundamental.data.clients.sec_xbrl.forward_signals_text import (
    FilingTextRecord,
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
    assert mda_growth["unit"] == "bps"
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
                    "unit": "bps",
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
                    "unit": "bps",
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
