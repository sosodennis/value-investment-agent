import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Reliability mapping for financial news sources
SOURCE_RELIABILITY_MAP = {
    "bloomberg.com": 1.0,
    "reuters.com": 1.0,
    "wsj.com": 1.0,
    "ft.com": 1.0,
    "sec.gov": 1.0,
    "cnbc.com": 0.8,
    "yahoo.com": 0.7,
    "finance.yahoo.com": 0.7,
    "marketwatch.com": 0.7,
    "barrons.com": 0.8,
    "investing.com": 0.6,
    "seekingalpha.com": 0.4,
    "reddit.com": 0.2,
    "twitter.com": 0.2,
    "x.com": 0.2,
    "nytimes.com": 0.9,
    "fortune.com": 0.8,
    "bbc.com": 0.9,
}


def get_source_reliability(url: str) -> float:
    """
    Calculate reliability score based on domain.
    """
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        return SOURCE_RELIABILITY_MAP.get(domain, 0.5)
    except Exception:
        return 0.5
