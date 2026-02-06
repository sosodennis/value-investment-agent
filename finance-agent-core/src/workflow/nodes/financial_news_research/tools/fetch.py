import asyncio
import logging
import time

import trafilatura

logger = logging.getLogger(__name__)


def fetch_clean_text(url: str, max_chars: int = 6000) -> str | None:
    """
    Fetch and clean article text using trafilatura (sync fallback).
    """
    # Sanitize URL: strip trailing colons and invisible Unicode chars
    url = url.rstrip(":")

    try:
        print(f"--- [Tool: fetch_clean_text] Fetching URL: {url} ---")
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning(f"Failed to fetch URL: {url}")
            return None

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not text:
            logger.warning(f"Failed to extract text from URL: {url}")
            return None

        print(
            f"--- [Tool: fetch_clean_text] Successfully extracted {len(text)} chars from {url} ---",
            flush=True,
        )
        return text[:max_chars]
    except Exception as e:
        logger.error(f"Error fetching/cleaning text from {url}: {e}")
        return None


async def fetch_clean_text_async(url: str, max_chars: int = 6000) -> str | None:
    """
    High-performance async fetch:
    1. httpx for true async non-blocking download (I/O bound)
    2. trafilatura for in-memory parsing (CPU bound but fast)
    """
    import httpx

    # Sanitize URL: strip trailing colons and invisible Unicode chars
    url = url.rstrip(":")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # 1. Async download (true non-blocking)
        dl_start = time.perf_counter()
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            print(f"--- [Fetch Async] 🚀 Requesting: {url} ---", flush=True)
            resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                print(
                    f"--- [Fetch Latency] ❌ FAILED: Status {resp.status_code} for {url} ---",
                    flush=True,
                )
                logger.warning(f"Failed to fetch {url}: Status {resp.status_code}")
                return None

            html_content = resp.text
        dl_end = time.perf_counter()

        # 2. Sync parse (in-memory, CPU bound but typically < 50ms)
        parse_start = time.perf_counter()
        text = await asyncio.to_thread(
            trafilatura.extract,
            html_content,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        parse_end = time.perf_counter()

        if not text:
            print(
                f"--- [Fetch Latency] ❌ FAILED: Extraction returned empty for {url} ---"
            )
            logger.warning(f"Failed to extract text from {url}")
            return None

        total_duration = parse_end - dl_start
        dl_duration = dl_end - dl_start
        parse_duration = parse_end - parse_start

        print(
            f"--- [Fetch Latency] {total_duration:.2f}s for {url} (Download: {dl_duration:.2f}s, Parse: {parse_duration:.2f}s) ---",
            flush=True,
        )
        print(f"--- [Fetch Async] ✅ Extracted {len(text)} chars ---", flush=True)
        return text[:max_chars]

    except httpx.RequestError as e:
        print(
            f"--- [Fetch Latency] ❌ FAILED: Network error for {url}: {e} ---",
            flush=True,
        )
        logger.error(f"Network error fetching {url}: {e}")
        return None
    except Exception as e:
        print(
            f"--- [Fetch Latency] ❌ FAILED: Unexpected error for {url}: {e} ---",
            flush=True,
        )
        logger.error(f"Parsing error for {url}: {e}")
        return None
