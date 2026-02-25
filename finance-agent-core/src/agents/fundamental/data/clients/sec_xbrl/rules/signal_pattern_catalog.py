from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

from .loader import load_merged_lexicon, load_pattern_catalog


@dataclass(frozen=True)
class MetricPatternSet:
    up: tuple[str, ...]
    down: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeSignalCatalog:
    signal_pattern_catalog: dict[str, MetricPatternSet]
    metric_retrieval_query: dict[str, str]
    fls_skip_signal_phrases: tuple[str, ...]


def build_fls_skip_signal_phrases(
    catalog: dict[str, MetricPatternSet],
) -> tuple[str, ...]:
    phrases = {
        phrase.lower()
        for pattern_set in catalog.values()
        for phrase in pattern_set.up + pattern_set.down
    }
    return tuple(sorted(phrases))


@lru_cache(maxsize=16)
def load_runtime_signal_catalog(*, sector: str | None = None) -> RuntimeSignalCatalog:
    pattern_catalog = load_pattern_catalog()
    lexicon = load_merged_lexicon(sector=sector)

    metric_order = OrderedDict.fromkeys(
        [*pattern_catalog.metrics.keys(), *lexicon.signals.keys()]
    )
    signal_pattern_catalog: dict[str, MetricPatternSet] = {}
    metric_retrieval_query: dict[str, str] = {}
    alias_phrases: list[str] = []

    for metric in metric_order:
        pattern_rule = pattern_catalog.metrics.get(metric)
        alias_entry = lexicon.signals.get(metric)
        aliases = alias_entry.aliases if alias_entry is not None else []

        positive_phrases = _normalize_phrase_list(
            pattern_rule.positive if pattern_rule is not None else []
        )
        negative_phrases = _normalize_phrase_list(
            pattern_rule.negative if pattern_rule is not None else []
        )
        signal_pattern_catalog[metric] = MetricPatternSet(
            up=positive_phrases,
            down=negative_phrases,
        )

        query_terms = _normalize_phrase_list(
            [
                *positive_phrases,
                *negative_phrases,
                *aliases,
                *lexicon.forward_cues,
            ]
        )
        metric_retrieval_query[metric] = " ".join(query_terms)
        alias_phrases.extend(aliases)

    fls_skip_signal_phrases = _normalize_phrase_list(
        [
            *build_fls_skip_signal_phrases(signal_pattern_catalog),
            *alias_phrases,
        ]
    )

    return RuntimeSignalCatalog(
        signal_pattern_catalog=signal_pattern_catalog,
        metric_retrieval_query=metric_retrieval_query,
        fls_skip_signal_phrases=fls_skip_signal_phrases,
    )


def _normalize_phrase_list(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    deduped: OrderedDict[str, None] = OrderedDict()
    for value in values:
        normalized = " ".join(value.split()).strip().lower()
        if not normalized:
            continue
        deduped[normalized] = None
    return tuple(deduped.keys())


_DEFAULT_RUNTIME_SIGNAL_CATALOG = load_runtime_signal_catalog()

FORWARD_SIGNAL_PATTERN_CATALOG: dict[str, MetricPatternSet] = (
    _DEFAULT_RUNTIME_SIGNAL_CATALOG.signal_pattern_catalog
)
METRIC_RETRIEVAL_QUERY: dict[str, str] = (
    _DEFAULT_RUNTIME_SIGNAL_CATALOG.metric_retrieval_query
)
FLS_SKIP_SIGNAL_PHRASES: tuple[str, ...] = (
    _DEFAULT_RUNTIME_SIGNAL_CATALOG.fls_skip_signal_phrases
)
