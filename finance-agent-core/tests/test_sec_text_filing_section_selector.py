from __future__ import annotations

from src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.filing_section_selector import (
    is_8k_form,
    refine_8k_analysis_text,
)


def test_refine_8k_analysis_text_prefers_item_sections_and_filters_noise() -> None:
    text = (
        "FORM 8-K. Item 1.01 Entry into a Material Definitive Agreement. "
        "Item 8.01 Other Events. Management expects higher revenue growth in 2026 "
        "and improving margins from operating leverage. "
        "SIGNATURES Pursuant to the requirements of the Securities Exchange Act, "
        "the registrant has duly caused this report to be signed."
    )

    result = refine_8k_analysis_text(text)

    assert "expects higher revenue growth" in result.text.lower()
    assert "signatures pursuant to the requirements" not in result.text.lower()
    assert result.sections_selected >= 1
    assert result.noise_sentences_skipped >= 1


def test_is_8k_form_is_case_insensitive() -> None:
    assert is_8k_form("8-k")
    assert is_8k_form("8-K")
    assert not is_8k_form("10-Q")
