from __future__ import annotations

from datetime import datetime, timezone

from ..application.ports import MarketDataProvider, ProviderFetch
from ..domain.market_datum import MarketDatum
from .free_consensus_web_parser import (
    extract_float_structured_first,
    extract_int_structured_first,
    fetch_html,
)


class TipRanksProvider(MarketDataProvider):
    name = "tipranks"
    license_note = (
        "TipRanks public web data. Verify Terms of Service before commercial use "
        "or redistribution."
    )

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        as_of = datetime.now(timezone.utc).isoformat()
        url = f"https://www.tipranks.com/stocks/{ticker_symbol.lower()}/forecast"
        html = fetch_html(url)

        target_mean, target_mean_extract = extract_float_structured_first(
            html,
            structured_keys=(
                "averagePriceTarget",
                "avgPriceTarget",
                "targetMeanPrice",
                "consensusPriceTarget",
            ),
            fallback_patterns=(
                r'"averagePriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r'"avgPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r"average\s+price\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
                r"price\s+target\s+of\s+\$([0-9][0-9.,]*)",
            ),
        )
        target_high, target_high_extract = extract_float_structured_first(
            html,
            structured_keys=(
                "highPriceTarget",
                "highestPriceTarget",
                "targetHighPrice",
            ),
            fallback_patterns=(
                r'"highPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r'"highestPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r"(?:highest|high)\s+price\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
            ),
        )
        target_low, target_low_extract = extract_float_structured_first(
            html,
            structured_keys=(
                "lowPriceTarget",
                "lowestPriceTarget",
                "targetLowPrice",
            ),
            fallback_patterns=(
                r'"lowPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r'"lowestPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r"(?:lowest|low)\s+price\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
            ),
        )
        analyst_count, analyst_extract = extract_int_structured_first(
            html,
            structured_keys=("numberOfAnalysts", "totalAnalysts", "analystCount"),
            fallback_patterns=(
                r'"numberOfAnalysts"\s*:\s*([0-9][0-9,]*)',
                r'"totalAnalysts"\s*:\s*([0-9][0-9,]*)',
                r"([0-9][0-9,]*)\s+analysts?\s+offering",
                r"based\s+on\s*([0-9][0-9,]*)\s+analysts?",
            ),
        )

        warnings: list[str] = []
        if target_mean is None:
            warnings.append(
                "tipranks target_mean_price parse missing "
                "[code=tipranks_target_mean_missing]"
            )

        datums = {
            "target_mean_price": self._datum(
                value=target_mean,
                as_of=as_of,
                source_detail=f"url={url};extract={target_mean_extract}",
            ),
            "target_high_price": self._datum(
                value=target_high,
                as_of=as_of,
                source_detail=f"url={url};extract={target_high_extract}",
            ),
            "target_low_price": self._datum(
                value=target_low,
                as_of=as_of,
                source_detail=f"url={url};extract={target_low_extract}",
            ),
            "target_analyst_count": self._datum(
                value=float(analyst_count) if analyst_count is not None else None,
                as_of=as_of,
                source_detail=f"url={url};extract={analyst_extract}",
            ),
        }
        return ProviderFetch(datums=datums, warnings=tuple(warnings))

    def _datum(
        self,
        *,
        value: float | None,
        as_of: str,
        source_detail: str,
    ) -> MarketDatum:
        quality_flags: tuple[str, ...] = ("missing",) if value is None else ()
        return MarketDatum(
            value=value,
            source=self.name,
            as_of=as_of,
            horizon="12m",
            source_detail=source_detail,
            quality_flags=quality_flags,
            license_note=self.license_note,
        )
