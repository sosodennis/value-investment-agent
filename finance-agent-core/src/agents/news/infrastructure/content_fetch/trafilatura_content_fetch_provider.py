import asyncio
import logging
import time

import httpx
import trafilatura

from src.agents.news.application.ports import FetchContentResult
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
_SHARED_ASYNC_CLIENT: httpx.AsyncClient | None = None


def _build_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=15.0)


async def get_shared_async_client() -> httpx.AsyncClient:
    global _SHARED_ASYNC_CLIENT
    if _SHARED_ASYNC_CLIENT is None or _SHARED_ASYNC_CLIENT.is_closed:
        _SHARED_ASYNC_CLIENT = _build_async_client()
    return _SHARED_ASYNC_CLIENT


async def close_shared_async_client() -> None:
    global _SHARED_ASYNC_CLIENT
    client = _SHARED_ASYNC_CLIENT
    _SHARED_ASYNC_CLIENT = None
    if client is not None and not client.is_closed:
        await client.aclose()


def fetch_clean_text(url: str, max_chars: int = 6000) -> str | None:
    """
    Fetch and clean article text using trafilatura (sync fallback).
    """
    # Sanitize URL: strip trailing colons and invisible Unicode chars
    url = url.rstrip(":")

    try:
        log_event(
            logger,
            event="news_fetch_sync_started",
            message="news sync fetch started",
            fields={"url": url},
        )
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            log_event(
                logger,
                event="news_fetch_sync_failed",
                message="news sync fetch failed due to empty download",
                level=logging.WARNING,
                error_code="NEWS_FETCH_SYNC_DOWNLOAD_EMPTY",
                fields={"url": url},
            )
            return None

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not text:
            log_event(
                logger,
                event="news_fetch_sync_failed",
                message="news sync fetch failed due to empty extraction",
                level=logging.WARNING,
                error_code="NEWS_FETCH_SYNC_EXTRACT_EMPTY",
                fields={"url": url},
            )
            return None

        log_event(
            logger,
            event="news_fetch_sync_completed",
            message="news sync fetch completed",
            fields={"url": url, "chars": len(text)},
        )
        return text[:max_chars]
    except Exception as exc:
        log_event(
            logger,
            event="news_fetch_sync_failed",
            message="news sync fetch failed",
            level=logging.ERROR,
            error_code="NEWS_FETCH_SYNC_FAILED",
            fields={"url": url, "exception": str(exc)},
        )
        return None


async def fetch_clean_text_async(url: str, max_chars: int = 6000) -> FetchContentResult:
    """
    High-performance async fetch:
    1. httpx for true async non-blocking download (I/O bound)
    2. trafilatura for in-memory parsing (CPU bound but fast)
    """
    # Sanitize URL: strip trailing colons and invisible Unicode chars
    url = url.rstrip(":")

    try:
        # 1. Async download (true non-blocking)
        dl_start = time.perf_counter()
        log_event(
            logger,
            event="news_fetch_async_started",
            message="news async fetch started",
            fields={"url": url},
        )
        client = await get_shared_async_client()
        resp = await client.get(url, headers=_DEFAULT_HEADERS)

        if resp.status_code != 200:
            log_event(
                logger,
                event="news_fetch_async_failed",
                message="news async fetch failed due to non-200 response",
                level=logging.WARNING,
                error_code="NEWS_FETCH_ASYNC_HTTP_STATUS",
                fields={"url": url, "status_code": resp.status_code},
            )
            return FetchContentResult.fail(
                code="http_status",
                reason=f"non-200 response: {resp.status_code}",
                http_status=resp.status_code,
            )

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
            log_event(
                logger,
                event="news_fetch_async_failed",
                message="news async fetch failed due to empty extraction",
                level=logging.WARNING,
                error_code="NEWS_FETCH_ASYNC_EXTRACT_EMPTY",
                fields={"url": url},
            )
            return FetchContentResult.fail(
                code="extract_empty",
                reason="empty extraction",
            )

        total_duration = parse_end - dl_start
        dl_duration = dl_end - dl_start
        parse_duration = parse_end - parse_start

        log_event(
            logger,
            event="news_fetch_async_completed",
            message="news async fetch completed",
            fields={
                "url": url,
                "chars": len(text),
                "total_seconds": round(total_duration, 3),
                "download_seconds": round(dl_duration, 3),
                "parse_seconds": round(parse_duration, 3),
            },
        )
        return FetchContentResult.ok(text[:max_chars])

    except httpx.RequestError as exc:
        log_event(
            logger,
            event="news_fetch_async_network_failed",
            message="news async fetch failed due to network error",
            level=logging.ERROR,
            error_code="NEWS_FETCH_ASYNC_NETWORK_FAILED",
            fields={"url": url, "exception": str(exc)},
        )
        return FetchContentResult.fail(
            code="network_error",
            reason=str(exc),
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_fetch_async_failed",
            message="news async fetch failed",
            level=logging.ERROR,
            error_code="NEWS_FETCH_ASYNC_FAILED",
            fields={"url": url, "exception": str(exc)},
        )
        return FetchContentResult.fail(
            code="provider_error",
            reason=str(exc),
        )
