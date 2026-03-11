from __future__ import annotations

from datetime import datetime, timezone

from ..application.ports import MarketDataProvider, ProviderFetch
from ..domain.market_datum import MarketDatum
from .free_consensus_web_parser import (
    extract_first_href_by_patterns,
    extract_first_match,
    extract_float_structured_first,
    extract_int_structured_first,
    fetch_html,
)


class MarketBeatProvider(MarketDataProvider):
    name = "marketbeat"
    license_note = (
        "MarketBeat public web data. Verify Terms of Service before commercial use "
        "or redistribution."
    )

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        as_of = datetime.now(timezone.utc).isoformat()
        page_url = self._resolve_stock_url(ticker_symbol)
        html = fetch_html(page_url)

        target_mean, target_mean_extract = extract_float_structured_first(
            html,
            structured_keys=(
                "consensusPriceTarget",
                "targetMeanPrice",
                "averagePriceTarget",
            ),
            fallback_patterns=(
                r'"consensusPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r"Average Price Target[^$]{0,40}\$([0-9][0-9.,]*)",
                r"Consensus Price Target[^$]{0,40}\$([0-9][0-9.,]*)",
            ),
        )
        target_high, target_high_extract = extract_float_structured_first(
            html,
            structured_keys=("highPriceTarget", "targetHighPrice"),
            fallback_patterns=(
                r'"highPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r"High Price Target[^$]{0,40}\$([0-9][0-9.,]*)",
            ),
        )
        target_low, target_low_extract = extract_float_structured_first(
            html,
            structured_keys=("lowPriceTarget", "targetLowPrice"),
            fallback_patterns=(
                r'"lowPriceTarget"\s*:\s*([0-9][0-9.,]*)',
                r"Low Price Target[^$]{0,40}\$([0-9][0-9.,]*)",
            ),
        )
        analyst_count, analyst_extract = extract_int_structured_first(
            html,
            structured_keys=("analystRatingsCount", "numberOfAnalysts", "analystCount"),
            fallback_patterns=(
                r'"analystRatingsCount"\s*:\s*([0-9][0-9,]*)',
                r"Based on\s*([0-9][0-9,]*)\s+analyst",
            ),
        )

        warnings: list[str] = []
        if target_mean is None:
            warnings.append(
                "marketbeat target_mean_price parse missing "
                "[code=marketbeat_target_mean_missing]"
            )

        datums = {
            "target_mean_price": self._datum(
                value=target_mean,
                as_of=as_of,
                source_detail=f"url={page_url};extract={target_mean_extract}",
            ),
            "target_high_price": self._datum(
                value=target_high,
                as_of=as_of,
                source_detail=f"url={page_url};extract={target_high_extract}",
            ),
            "target_low_price": self._datum(
                value=target_low,
                as_of=as_of,
                source_detail=f"url={page_url};extract={target_low_extract}",
            ),
            "target_analyst_count": self._datum(
                value=float(analyst_count) if analyst_count is not None else None,
                as_of=as_of,
                source_detail=f"url={page_url};extract={analyst_extract}",
            ),
        }
        return ProviderFetch(datums=datums, warnings=tuple(warnings))

    def _resolve_stock_url(self, ticker_symbol: str) -> str:
        search_url = f"https://www.marketbeat.com/stocks/?query={ticker_symbol.upper()}"
        html = fetch_html(search_url)
        path = extract_first_href_by_patterns(
            html,
            (
                r"^/stocks/[A-Za-z]+/[A-Za-z0-9.-]+/?$",
                r"^/stocks/[^\"']+/?$",
            ),
        )
        if isinstance(path, str) and path:
            return f"https://www.marketbeat.com{path}"

        path = extract_first_match(
            html,
            (
                r'href="(/stocks/[A-Za-z]+/[A-Za-z0-9.-]+/)"',
                r'href="(/stocks/[^"]+/)"',
            ),
        )
        if isinstance(path, str) and path:
            return f"https://www.marketbeat.com{path}"
        return f"https://www.marketbeat.com/stocks/NASDAQ/{ticker_symbol.upper()}/"

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
