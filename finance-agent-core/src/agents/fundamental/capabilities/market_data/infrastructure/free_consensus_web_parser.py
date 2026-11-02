from __future__ import annotations

import json
import re
from collections.abc import Iterator
from html import unescape
from html.parser import HTMLParser

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, RequestException, Timeout
from urllib3.util import Retry

DEFAULT_HTTP_TIMEOUT_SECONDS = 4.0
DEFAULT_HTTP_MAX_RETRIES = 2
DEFAULT_HTTP_BACKOFF_SECONDS = 0.3
RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
_HTTP_SESSION: requests.Session | None = None


class ConsensusFetchError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        url: str,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        self.code = code
        self.url = url
        self.status_code = status_code
        self.reason = reason
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        segments = [f"code={self.code}", f"url={self.url}"]
        if isinstance(self.status_code, int):
            segments.append(f"status={self.status_code}")
        if isinstance(self.reason, str) and self.reason.strip():
            segments.append(f"reason={self.reason.strip()}")
        return ";".join(segments)


def fetch_html(url: str) -> str:
    try:
        response = _http_session().get(url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        raise ConsensusFetchError(
            code=_classify_http_error_code(status_code),
            url=url,
            status_code=status_code,
            reason=str(exc),
        ) from exc
    except Timeout as exc:
        raise ConsensusFetchError(
            code="provider_timeout",
            url=url,
            reason=str(exc),
        ) from exc
    except RequestsConnectionError as exc:
        raise ConsensusFetchError(
            code=_classify_connection_error_code(exc),
            url=url,
            reason=str(exc),
        ) from exc
    except RequestException as exc:
        raise ConsensusFetchError(
            code="provider_request_error",
            url=url,
            reason=str(exc),
        ) from exc


def extract_float_structured_first(
    text: str,
    *,
    structured_keys: tuple[str, ...],
    fallback_patterns: tuple[str, ...],
) -> tuple[float | None, str]:
    structured_value = extract_first_float_from_structured_data(text, structured_keys)
    if structured_value is not None:
        return structured_value, "structured_json"
    fallback_value = extract_first_float(text, fallback_patterns)
    if fallback_value is not None:
        return fallback_value, "text_pattern"
    return None, "missing"


def extract_int_structured_first(
    text: str,
    *,
    structured_keys: tuple[str, ...],
    fallback_patterns: tuple[str, ...],
) -> tuple[int | None, str]:
    structured_value = extract_first_int_from_structured_data(text, structured_keys)
    if structured_value is not None:
        return structured_value, "structured_json"
    fallback_value = extract_first_int(text, fallback_patterns)
    if fallback_value is not None:
        return fallback_value, "text_pattern"
    return None, "missing"


def extract_first_float(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = _coerce_float(match.group(1))
        if value is not None:
            return value
    return None


def extract_first_int(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = _coerce_int(match.group(1))
        if value is not None:
            return value
    return None


def extract_first_match(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_first_float_from_structured_data(
    text: str,
    key_candidates: tuple[str, ...],
) -> float | None:
    key_set = {item.casefold() for item in key_candidates if item}
    for candidate in _iter_structured_values(text, key_set):
        value = _coerce_structured_float(candidate)
        if value is not None:
            return value
    return None


def extract_first_int_from_structured_data(
    text: str,
    key_candidates: tuple[str, ...],
) -> int | None:
    key_set = {item.casefold() for item in key_candidates if item}
    for candidate in _iter_structured_values(text, key_set):
        value = _coerce_structured_int(candidate)
        if value is not None:
            return value
    return None


def extract_first_href_by_patterns(
    text: str,
    href_patterns: tuple[str, ...],
) -> str | None:
    compiled_patterns = tuple(
        re.compile(pattern, re.IGNORECASE) for pattern in href_patterns
    )
    for href in _extract_hrefs(text):
        for pattern in compiled_patterns:
            if pattern.search(href):
                return href
    return None


def _http_session() -> requests.Session:
    global _HTTP_SESSION
    if _HTTP_SESSION is not None:
        return _HTTP_SESSION
    session = requests.Session()
    retry = Retry(
        total=DEFAULT_HTTP_MAX_RETRIES,
        connect=DEFAULT_HTTP_MAX_RETRIES,
        read=DEFAULT_HTTP_MAX_RETRIES,
        status=DEFAULT_HTTP_MAX_RETRIES,
        backoff_factor=DEFAULT_HTTP_BACKOFF_SECONDS,
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    _HTTP_SESSION = session
    return session


def _iter_structured_values(
    text: str,
    key_set: set[str],
) -> Iterator[object]:
    if not key_set:
        return
    for payload in _extract_script_payloads(text):
        parsed = _try_parse_json_payload(payload)
        if parsed is None:
            continue
        yield from _iter_values_for_keys(parsed, key_set)


def _extract_script_payloads(text: str) -> tuple[str, ...]:
    parser = _JsonScriptCollector()
    parser.feed(text)
    parser.close()
    return tuple(parser.payloads)


def _try_parse_json_payload(payload: str) -> object | None:
    normalized = unescape(payload.strip())
    if not normalized:
        return None
    for candidate in _json_candidates(normalized):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, str):
            nested = parsed.strip()
            if nested.startswith("{") or nested.startswith("["):
                try:
                    reparsed = json.loads(nested)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(reparsed, dict | list):
                        return reparsed
        if isinstance(parsed, dict | list):
            return parsed
    return None


def _json_candidates(payload: str) -> tuple[str, ...]:
    if not payload:
        return ()
    trimmed = payload.strip()
    candidates = [trimmed]
    if trimmed.startswith("<!--") and trimmed.endswith("-->"):
        candidates.append(trimmed[4:-3].strip())
    if trimmed.startswith("//<![CDATA[") and trimmed.endswith("//]]>"):
        candidates.append(trimmed[11:-5].strip())
    return tuple(dict.fromkeys(item for item in candidates if item))


def _iter_values_for_keys(node: object, key_set: set[str]) -> Iterator[object]:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized_key = str(key).casefold()
            if normalized_key in key_set:
                yield value
            yield from _iter_values_for_keys(value, key_set)
        return
    if isinstance(node, list):
        for item in node:
            yield from _iter_values_for_keys(item, key_set)


def _coerce_structured_float(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        value = float(raw)
        if value != value:
            return None
        return value
    if isinstance(raw, str):
        return _coerce_float(raw)
    return None


def _coerce_structured_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        return int(raw) if raw >= 0 else None
    if isinstance(raw, str):
        return _coerce_int(raw)
    return None


def _extract_hrefs(text: str) -> tuple[str, ...]:
    parser = _HrefCollector()
    parser.feed(text)
    parser.close()
    dedup_hrefs = tuple(dict.fromkeys(href for href in parser.hrefs if href))
    return dedup_hrefs


class _JsonScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_active = False
        self._buffer: list[str] = []
        self.payloads: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attrs_map = {key.lower(): value for key, value in attrs if key}
        script_type = (attrs_map.get("type") or "").casefold()
        script_id = (attrs_map.get("id") or "").casefold()
        is_json_payload = (
            script_type in {"application/ld+json", "application/json"}
            or script_id == "__next_data__"
        )
        if not is_json_payload:
            return
        self._capture_active = True
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture_active:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script":
            return
        if not self._capture_active:
            return
        payload = "".join(self._buffer).strip()
        if payload:
            self.payloads.append(payload)
        self._capture_active = False
        self._buffer = []


class _HrefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() != "href" or value is None:
                continue
            self.hrefs.append(value.strip())
            break


def _classify_http_error_code(status_code: int | None) -> str:
    if status_code == 401 or status_code == 403:
        return "provider_blocked_http"
    if status_code == 404:
        return "provider_page_missing"
    if status_code == 429:
        return "provider_rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "provider_upstream_error"
    return "provider_http_error"


def _classify_connection_error_code(exc: RequestsConnectionError) -> str:
    message = str(exc).casefold()
    if "name resolution" in message or "failed to resolve" in message:
        return "provider_dns_error"
    if "connection refused" in message:
        return "provider_connection_refused"
    return "provider_connection_error"


def _coerce_float(raw: str) -> float | None:
    normalized = raw.replace("$", "").replace(",", "").strip()
    if not normalized:
        return None
    try:
        value = float(normalized)
    except ValueError:
        return None
    if value != value:
        return None
    return value


def _coerce_int(raw: str) -> int | None:
    normalized = raw.replace(",", "").strip()
    if not normalized:
        return None
    try:
        value = int(float(normalized))
    except ValueError:
        return None
    if value < 0:
        return None
    return value
