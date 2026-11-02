from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import yaml

from .schema import LexiconConfig, PatternCatalogConfig, SignalLexiconEntry

_RULES_ROOT = Path(__file__).resolve().parent


def load_merged_lexicon(
    *,
    sector: str | None = None,
    rules_root: Path | None = None,
) -> LexiconConfig:
    root = rules_root or _RULES_ROOT
    global_lexicon = _load_lexicon_file(root / "lexicons" / "global.yml")
    if sector is None:
        return global_lexicon

    sector_file = root / "lexicons" / "sectors" / f"{sector.lower().strip()}.yml"
    if not sector_file.exists():
        return global_lexicon
    sector_lexicon = _load_lexicon_file(sector_file)
    return _merge_lexicons(global_lexicon, sector_lexicon)


def load_pattern_catalog(*, rules_root: Path | None = None) -> PatternCatalogConfig:
    root = rules_root or _RULES_ROOT
    raw = _read_yaml_dict(root / "patterns" / "global.yml")
    return PatternCatalogConfig.model_validate(raw)


def _load_lexicon_file(path: Path) -> LexiconConfig:
    raw = _read_yaml_dict(path)
    return LexiconConfig.model_validate(raw)


def _read_yaml_dict(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Rule file must be a mapping: {path}")
    return raw


def _merge_lexicons(base: LexiconConfig, overlay: LexiconConfig) -> LexiconConfig:
    merged_forward_cues = _merge_unique(base.forward_cues, overlay.forward_cues)
    merged_signals: dict[str, SignalLexiconEntry] = {}
    keys = OrderedDict.fromkeys([*base.signals.keys(), *overlay.signals.keys()])
    for metric in keys:
        base_aliases = base.signals.get(metric, SignalLexiconEntry()).aliases
        overlay_aliases = overlay.signals.get(metric, SignalLexiconEntry()).aliases
        merged_signals[metric] = SignalLexiconEntry(
            aliases=_merge_unique(base_aliases, overlay_aliases)
        )
    return LexiconConfig(
        version=max(base.version, overlay.version),
        extends=overlay.extends or base.extends,
        forward_cues=merged_forward_cues,
        signals=merged_signals,
    )


def _merge_unique(primary: list[str], secondary: list[str]) -> list[str]:
    merged = OrderedDict.fromkeys([*primary, *secondary])
    return [item for item in merged if isinstance(item, str) and item.strip()]
