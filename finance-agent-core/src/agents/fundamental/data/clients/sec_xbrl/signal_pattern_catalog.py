from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricPatternSet:
    up: tuple[str, ...]
    down: tuple[str, ...]


FORWARD_SIGNAL_PATTERN_CATALOG: dict[str, MetricPatternSet] = {
    "growth_outlook": MetricPatternSet(
        up=(
            "raised guidance",
            "raise guidance",
            "increase guidance",
            "guidance increased",
            "guidance raised",
            "strong demand",
            "accelerating growth",
            "record backlog",
            "expect higher revenue",
            "expect revenue growth",
            "expect revenue to grow",
            "expect growth to continue",
            "expect demand to remain strong",
            "expect demand to increase",
            "revenue growth outlook",
            "sales growth outlook",
            "continued growth",
            "growth momentum",
            "top line growth",
            "advertising revenue growth",
        ),
        down=(
            "lowered guidance",
            "lower guidance",
            "decrease guidance",
            "guidance lowered",
            "decelerating growth",
            "soft demand",
            "declining demand",
            "revenue headwind",
            "expect lower revenue",
            "slower growth",
            "expect growth to slow",
            "expect demand to soften",
            "macroeconomic headwind",
            "foreign exchange headwind",
            "fx headwind",
            "softening demand",
        ),
    ),
    "margin_outlook": MetricPatternSet(
        up=(
            "margin expansion",
            "operating leverage",
            "cost discipline",
            "pricing power",
            "improved margin",
            "improving margin",
            "expand margin",
            "margin improvement",
            "improve profitability",
            "profitability improvement",
            "efficiency improvement",
            "expense discipline",
            "operating margin expansion",
        ),
        down=(
            "margin pressure",
            "cost inflation",
            "higher input costs",
            "margin compression",
            "weaker margin",
            "contracting margin",
            "margin contraction",
            "higher costs",
            "costs to increase",
            "increase in costs",
            "expense headwind",
            "higher depreciation expense",
            "increase in depreciation expense",
            "operating margin decline",
            "profitability pressure",
        ),
    ),
}


METRIC_RETRIEVAL_QUERY: dict[str, str] = {
    "growth_outlook": (
        "expected revenue growth sales guidance demand acceleration outlook forecast "
        "top line growth advertising revenue growth fx headwind macroeconomic headwind"
    ),
    "margin_outlook": (
        "operating margin gross margin profitability cost inflation pricing outlook guidance "
        "depreciation expense efficiency costs pressure leverage"
    ),
}


def build_fls_skip_signal_phrases(
    catalog: dict[str, MetricPatternSet],
) -> tuple[str, ...]:
    phrases = {
        phrase.lower()
        for pattern_set in catalog.values()
        for phrase in pattern_set.up + pattern_set.down
    }
    return tuple(sorted(phrases))
