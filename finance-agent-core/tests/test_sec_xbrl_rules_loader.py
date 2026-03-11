from __future__ import annotations

from src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.matching.rules.loader import (
    load_merged_lexicon,
    load_pattern_catalog,
)


def test_load_pattern_catalog_reads_global_patterns() -> None:
    catalog = load_pattern_catalog()

    assert catalog.version == 1
    assert "growth_outlook" in catalog.metrics
    assert "margin_outlook" in catalog.metrics
    assert catalog.metrics["growth_outlook"].forward_only is True


def test_load_merged_lexicon_without_sector_reads_global_only() -> None:
    lexicon = load_merged_lexicon()

    assert lexicon.version == 1
    assert "expect" in lexicon.forward_cues
    assert "growth_outlook" in lexicon.signals
    assert "revenue growth" in lexicon.signals["growth_outlook"].aliases


def test_load_merged_lexicon_with_sector_merges_aliases_and_cues() -> None:
    lexicon = load_merged_lexicon(sector="technology")

    assert "expect" in lexicon.forward_cues
    assert "margin_outlook" in lexicon.signals
    assert "gross margin" in lexicon.signals["margin_outlook"].aliases
    assert "cloud mix shift" in lexicon.signals["margin_outlook"].aliases


def test_load_merged_lexicon_with_unknown_sector_falls_back_to_global() -> None:
    unknown = load_merged_lexicon(sector="unknown_sector")
    global_only = load_merged_lexicon()

    assert unknown.model_dump() == global_only.model_dump()


def test_load_merged_lexicon_supports_additional_sector_overlays() -> None:
    financials = load_merged_lexicon(sector="financials")
    consumer = load_merged_lexicon(sector="consumer_discretionary")

    assert "net interest income" in financials.signals["growth_outlook"].aliases
    assert "deposit margin compression" in financials.signals["margin_outlook"].aliases
    assert "net sales growth" in consumer.signals["growth_outlook"].aliases
    assert (
        "fulfillment network efficiencies" in consumer.signals["margin_outlook"].aliases
    )
