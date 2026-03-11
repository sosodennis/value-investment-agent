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


class InvestingProvider(MarketDataProvider):
    name = "investing"
    license_note = (
        "Investing.com public web data. Verify Terms of Service before commercial "
        "use or redistribution."
    )

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        as_of = datetime.now(timezone.utc).isoformat()
        page_url = self._resolve_consensus_url(ticker_symbol)
        html = fetch_html(page_url)

        target_mean, target_mean_extract = extract_float_structured_first(
            html,
            structured_keys=(
                "targetMeanPrice",
                "averagePriceTarget",
                "avgPriceTarget",
            ),
            fallback_patterns=(
                r'"targetMeanPrice"\s*:\s*([0-9][0-9.,]*)',
                r'"average"\s*:\s*"?\$?([0-9][0-9.,]*)"?',
                r"average(?:\s+price)?\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
                r"12m\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
            ),
        )
        target_high, target_high_extract = extract_float_structured_first(
            html,
            structured_keys=("targetHighPrice", "highPriceTarget"),
            fallback_patterns=(
                r'"targetHighPrice"\s*:\s*([0-9][0-9.,]*)',
                r'"high"\s*:\s*"?\$?([0-9][0-9.,]*)"?',
                r"high(?:\s+price)?\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
            ),
        )
        target_low, target_low_extract = extract_float_structured_first(
            html,
            structured_keys=("targetLowPrice", "lowPriceTarget"),
            fallback_patterns=(
                r'"targetLowPrice"\s*:\s*([0-9][0-9.,]*)',
                r'"low"\s*:\s*"?\$?([0-9][0-9.,]*)"?',
                r"low(?:\s+price)?\s+target[^$]{0,24}\$([0-9][0-9.,]*)",
            ),
        )
        analyst_count, analyst_extract = extract_int_structured_first(
            html,
            structured_keys=("numberOfAnalysts", "analystCount", "totalAnalysts"),
            fallback_patterns=(
                r'"numberOfAnalysts"\s*:\s*([0-9][0-9,]*)',
                r"([0-9][0-9,]*)\s+analysts",
            ),
        )

        warnings: list[str] = []
        if target_mean is None:
            warnings.append(
                "investing target_mean_price parse missing "
                "[code=investing_target_mean_missing]"
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

    def _resolve_consensus_url(self, ticker_symbol: str) -> str:
        search_url = f"https://www.investing.com/search/?q={ticker_symbol.upper()}"
        html = fetch_html(search_url)
        path = extract_first_href_by_patterns(
            html,
            (r"^/equities/[^\"']+-consensus-estimates/?$",),
        )
        if isinstance(path, str) and path:
            return f"https://www.investing.com{path}"

        path = extract_first_match(
            html,
            (r'href="(/equities/[^"]+-consensus-estimates)"',),
        )
        if isinstance(path, str) and path:
            return f"https://www.investing.com{path}"
        return (
            "https://www.investing.com/equities/"
            f"{ticker_symbol.lower()}-consensus-estimates"
        )

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
