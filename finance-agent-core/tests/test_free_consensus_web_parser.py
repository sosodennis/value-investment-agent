from __future__ import annotations

import requests

from src.agents.fundamental.market_data.infrastructure.free_consensus_web_parser import (
    ConsensusFetchError,
    extract_first_float_from_structured_data,
    extract_first_href_by_patterns,
    extract_first_int_from_structured_data,
    extract_float_structured_first,
    fetch_html,
)


def test_extract_structured_data_from_json_ld_script() -> None:
    html = """
    <html><head></head><body>
      <script type="application/ld+json">
        {"quote":{"averagePriceTarget":"245.50","numberOfAnalysts":"33"}}
      </script>
    </body></html>
    """

    target = extract_first_float_from_structured_data(
        html,
        ("averagePriceTarget", "targetMeanPrice"),
    )
    analysts = extract_first_int_from_structured_data(
        html,
        ("numberOfAnalysts",),
    )

    assert target == 245.50
    assert analysts == 33


def test_extract_float_structured_first_falls_back_to_text_pattern() -> None:
    html = '<div data-blob=\'{"avgPriceTarget":"221.40"}\'></div>'

    value, method = extract_float_structured_first(
        html,
        structured_keys=("averagePriceTarget",),
        fallback_patterns=(r'"avgPriceTarget"\s*:\s*"([0-9][0-9.,]*)"',),
    )

    assert value == 221.40
    assert method == "text_pattern"


def test_extract_first_href_by_patterns_from_anchor_tags() -> None:
    html = """
    <a href="/equities/apple-consensus-estimates">AAPL consensus</a>
    <a href="/equities/apple-earnings">AAPL earnings</a>
    """
    href = extract_first_href_by_patterns(
        html,
        (r"^/equities/[^\"']+-consensus-estimates/?$",),
    )
    assert href == "/equities/apple-consensus-estimates"


def test_fetch_html_raises_coded_consensus_fetch_error_for_403(monkeypatch) -> None:
    response = requests.Response()
    response.status_code = 403
    response.url = "https://www.tipranks.com/stocks/aapl/forecast"
    error = requests.HTTPError("403 Client Error", response=response)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            raise error

    class _FakeSession:
        def get(self, url: str, *, timeout: float):  # noqa: ARG002
            assert "tipranks" in url
            return _FakeResponse()

    monkeypatch.setattr(
        "src.agents.fundamental.market_data.infrastructure.free_consensus_web_parser._http_session",
        lambda: _FakeSession(),
    )

    try:
        fetch_html("https://www.tipranks.com/stocks/aapl/forecast")
    except ConsensusFetchError as exc:
        assert exc.code == "provider_blocked_http"
        assert exc.status_code == 403
    else:
        raise AssertionError("expected ConsensusFetchError")
