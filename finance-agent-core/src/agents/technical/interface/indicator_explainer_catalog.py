from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicatorExplainerCatalogEntry:
    signal: str
    plain_name: str
    family: str
    priority: int
    what_it_measures: str
    why_it_matters: str


_INDICATOR_EXPLAINER_CATALOG: dict[str, IndicatorExplainerCatalogEntry] = {
    "ADX_14": IndicatorExplainerCatalogEntry(
        signal="ADX_14",
        plain_name="趨勢強度",
        family="classic",
        priority=20,
        what_it_measures="This measures how strong the current trend is, without saying whether it is up or down.",
        why_it_matters="Stronger trend readings make continuation signals more believable, while weaker readings often mean a choppier market.",
    ),
    "ATRP_14": IndicatorExplainerCatalogEntry(
        signal="ATRP_14",
        plain_name="相對波動幅度",
        family="classic",
        priority=30,
        what_it_measures="This shows how large recent price swings are relative to the asset price.",
        why_it_matters="It helps users judge whether the market is moving calmly or with enough volatility to increase risk.",
    ),
    "ATR_14": IndicatorExplainerCatalogEntry(
        signal="ATR_14",
        plain_name="平均價格波動",
        family="classic",
        priority=50,
        what_it_measures="This shows the average absolute price movement over the last 14 bars in price units.",
        why_it_matters="It gives a practical sense of how much the asset usually moves, which helps size the move behind the headline direction.",
    ),
    "BB_BANDWIDTH_20": IndicatorExplainerCatalogEntry(
        signal="BB_BANDWIDTH_20",
        plain_name="波動壓縮程度",
        family="classic",
        priority=40,
        what_it_measures="This measures how wide or narrow the Bollinger Bands are, which is a quick proxy for volatility expansion or compression.",
        why_it_matters="Tighter bandwidth often means price is coiling, while wider bandwidth means volatility is already expanding.",
    ),
    "FD_Z_SCORE": IndicatorExplainerCatalogEntry(
        signal="FD_Z_SCORE",
        plain_name="分數差分偏離度",
        family="quant",
        priority=25,
        what_it_measures="This shows how far the fractional-differenced signal is from its own normal range.",
        why_it_matters="Large positive or negative readings can signal statistical stretch, while readings near zero usually mean conditions are closer to normal.",
    ),
    "FD_OPTIMAL_D": IndicatorExplainerCatalogEntry(
        signal="FD_OPTIMAL_D",
        plain_name="分數差分強度",
        family="quant",
        priority=10,
        what_it_measures="This estimates how much trend or memory needs to be removed to make the series more stable.",
        why_it_matters="It helps explain whether the market data still carries persistent structure instead of behaving like short-lived noise.",
    ),
    "FD_ADF_STAT": IndicatorExplainerCatalogEntry(
        signal="FD_ADF_STAT",
        plain_name="平穩性檢查",
        family="quant",
        priority=35,
        what_it_measures="This is a stationarity test score after fractional differencing.",
        why_it_matters="A stronger stationarity result supports the idea that the transformed signal is stable enough to interpret with more trust.",
    ),
}


def get_indicator_explainer_entry(
    signal: str,
) -> IndicatorExplainerCatalogEntry | None:
    return _INDICATOR_EXPLAINER_CATALOG.get(signal)


def iter_indicator_explainer_entries() -> tuple[IndicatorExplainerCatalogEntry, ...]:
    return tuple(
        sorted(_INDICATOR_EXPLAINER_CATALOG.values(), key=lambda item: item.priority)
    )
