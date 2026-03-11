from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from src.shared.kernel.types import JSONObject, JSONValue

_UNKNOWN_CACHE_TOKEN = "unknown"
_CACHE_NAMESPACE = "fundamental:sec_xbrl"
_PAYLOAD_ALIAS_PREFIX = "payload-alias"


@dataclass(frozen=True)
class FilingCacheCoordinates:
    cik: str
    accession: str
    taxonomy_version: str

    @classmethod
    def unknown(cls) -> FilingCacheCoordinates:
        return cls(
            cik=_UNKNOWN_CACHE_TOKEN,
            accession=_UNKNOWN_CACHE_TOKEN,
            taxonomy_version=_UNKNOWN_CACHE_TOKEN,
        )


@dataclass(frozen=True)
class FilingCacheLookupResult:
    payload: JSONObject | None
    hit: bool
    layer: str | None
    alias_layer: str | None
    alias_key: str
    payload_key: str | None
    lookup_ms: float


class _RedisClientLike(Protocol):
    def get(self, name: str) -> str | bytes | None: ...

    def setex(self, name: str, time: int, value: str) -> object: ...

    def ping(self) -> object: ...


class FilingCacheService:
    def __init__(
        self,
        *,
        l1_ttl_seconds: int = 600,
        l2_ttl_seconds: int = 1800,
        l3_ttl_seconds: int = 21600,
        redis_url: str | None = None,
        l3_cache_dir: str | None = None,
        l2_enabled: bool = True,
        l3_enabled: bool = True,
    ) -> None:
        self._l1_ttl_seconds = max(1, l1_ttl_seconds)
        self._l2_ttl_seconds = max(1, l2_ttl_seconds)
        self._l3_ttl_seconds = max(1, l3_ttl_seconds)

        self._l1: dict[str, tuple[float, JSONObject]] = {}
        self._l1_stats: dict[str, int] = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "l3_hits": 0,
            "l3_misses": 0,
        }

        resolved_redis_url = redis_url.strip() if isinstance(redis_url, str) else ""
        self._redis_client: _RedisClientLike | None = None
        if l2_enabled and resolved_redis_url:
            self._redis_client = _build_redis_client(resolved_redis_url)

        self._l3_cache_dir: Path | None = None
        if l3_enabled:
            root = (
                Path(l3_cache_dir)
                if isinstance(l3_cache_dir, str) and l3_cache_dir.strip()
                else Path("/tmp/fundamental_xbrl_cache")
            )
            self._l3_cache_dir = root
            root.mkdir(parents=True, exist_ok=True)

    def stats_snapshot(self) -> dict[str, int]:
        return dict(self._l1_stats)

    def clear(self) -> None:
        self._l1.clear()
        for key in list(self._l1_stats):
            self._l1_stats[key] = 0

    def build_payload_key(
        self,
        *,
        coordinates: FilingCacheCoordinates,
        field_key: str,
    ) -> str:
        cik = _normalize_cache_token(coordinates.cik)
        accession = _normalize_cache_token(coordinates.accession)
        taxonomy_version = _normalize_cache_token(coordinates.taxonomy_version)
        normalized_field_key = _normalize_cache_token(field_key)
        return (
            f"{_CACHE_NAMESPACE}:payload:"
            f"{cik}:{accession}:{taxonomy_version}:{normalized_field_key}"
        )

    def build_alias_key(
        self,
        *,
        ticker: str,
        years: int,
        field_key: str,
    ) -> str:
        normalized_ticker = _normalize_cache_token(ticker.upper())
        normalized_field_key = _normalize_cache_token(field_key)
        normalized_years = max(1, int(years))
        return (
            f"{_CACHE_NAMESPACE}:{_PAYLOAD_ALIAS_PREFIX}:"
            f"{normalized_ticker}:{normalized_years}:{normalized_field_key}"
        )

    def lookup_payload(
        self,
        *,
        ticker: str,
        years: int,
        field_key: str,
    ) -> FilingCacheLookupResult:
        started = time.perf_counter()
        alias_key = self.build_alias_key(
            ticker=ticker, years=years, field_key=field_key
        )
        alias_payload, alias_layer = self._get_object(alias_key)
        payload_key: str | None = None
        if isinstance(alias_payload, dict):
            candidate = alias_payload.get("payload_key")
            if isinstance(candidate, str) and candidate:
                payload_key = candidate

        if payload_key is None:
            return FilingCacheLookupResult(
                payload=None,
                hit=False,
                layer=None,
                alias_layer=alias_layer,
                alias_key=alias_key,
                payload_key=None,
                lookup_ms=(time.perf_counter() - started) * 1000.0,
            )

        payload, payload_layer = self._get_object(payload_key)
        return FilingCacheLookupResult(
            payload=payload,
            hit=payload is not None,
            layer=payload_layer,
            alias_layer=alias_layer,
            alias_key=alias_key,
            payload_key=payload_key,
            lookup_ms=(time.perf_counter() - started) * 1000.0,
        )

    def store_payload(
        self,
        *,
        ticker: str,
        years: int,
        field_key: str,
        coordinates: FilingCacheCoordinates,
        payload: JSONObject,
    ) -> str:
        payload_key = self.build_payload_key(
            coordinates=coordinates,
            field_key=field_key,
        )
        alias_key = self.build_alias_key(
            ticker=ticker, years=years, field_key=field_key
        )
        alias_payload: JSONObject = {
            "payload_key": payload_key,
            "cik": _normalize_cache_token(coordinates.cik),
            "accession": _normalize_cache_token(coordinates.accession),
            "taxonomy_version": _normalize_cache_token(coordinates.taxonomy_version),
        }

        self._set_object(payload_key, payload)
        self._set_object(alias_key, alias_payload)
        return payload_key

    def _get_object(self, key: str) -> tuple[JSONObject | None, str | None]:
        payload = self._l1_get(key)
        if payload is not None:
            self._l1_stats["l1_hits"] += 1
            return payload, "L1"
        self._l1_stats["l1_misses"] += 1

        payload = self._l2_get(key)
        if payload is not None:
            self._l1_stats["l2_hits"] += 1
            self._l1[key] = (time.time() + float(self._l1_ttl_seconds), payload)
            return payload, "L2"
        self._l1_stats["l2_misses"] += 1

        payload = self._l3_get(key)
        if payload is not None:
            self._l1_stats["l3_hits"] += 1
            self._l1[key] = (time.time() + float(self._l1_ttl_seconds), payload)
            if self._redis_client is not None:
                self._l2_set(key, payload)
            return payload, "L3"
        self._l1_stats["l3_misses"] += 1
        return None, None

    def _set_object(self, key: str, payload: JSONObject) -> None:
        self._l1[key] = (time.time() + float(self._l1_ttl_seconds), payload)
        self._l2_set(key, payload)
        self._l3_set(key, payload)

    def _l1_get(self, key: str) -> JSONObject | None:
        entry = self._l1.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.time():
            self._l1.pop(key, None)
            return None
        return dict(payload)

    def _l2_get(self, key: str) -> JSONObject | None:
        client = self._redis_client
        if client is None:
            return None
        try:
            raw = client.get(key)
            if raw is None:
                return None
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not isinstance(text, str):
                return None
            parsed = json.loads(text)
            return _as_json_object(parsed)
        except Exception:
            return None

    def _l2_set(self, key: str, payload: JSONObject) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            client.setex(key, self._l2_ttl_seconds, encoded)
        except Exception:
            return

    def _l3_get(self, key: str) -> JSONObject | None:
        cache_dir = self._l3_cache_dir
        if cache_dir is None:
            return None
        path = cache_dir / f"{_stable_key_hash(key)}.json"
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return None
            expires_at = parsed.get("expires_at_epoch")
            if not isinstance(expires_at, int | float):
                return None
            if float(expires_at) < time.time():
                path.unlink(missing_ok=True)
                return None
            payload = parsed.get("payload")
            return _as_json_object(payload)
        except Exception:
            return None

    def _l3_set(self, key: str, payload: JSONObject) -> None:
        cache_dir = self._l3_cache_dir
        if cache_dir is None:
            return
        path = cache_dir / f"{_stable_key_hash(key)}.json"
        tmp_path = cache_dir / f"{_stable_key_hash(key)}.tmp"
        envelope: JSONObject = {
            "key": key,
            "expires_at_epoch": time.time() + float(self._l3_ttl_seconds),
            "payload": payload,
        }
        try:
            encoded = json.dumps(envelope, ensure_ascii=True, separators=(",", ":"))
            tmp_path.write_text(encoded, encoding="utf-8")
            tmp_path.replace(path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            return


def build_default_filing_cache_service() -> FilingCacheService:
    return FilingCacheService(
        l1_ttl_seconds=_env_int("FUNDAMENTAL_XBRL_CACHE_L1_TTL_SECONDS", 900),
        l2_ttl_seconds=_env_int("FUNDAMENTAL_XBRL_CACHE_L2_TTL_SECONDS", 3600),
        l3_ttl_seconds=_env_int("FUNDAMENTAL_XBRL_CACHE_L3_TTL_SECONDS", 21600),
        redis_url=os.getenv("FUNDAMENTAL_XBRL_REDIS_URL"),
        l3_cache_dir=os.getenv("FUNDAMENTAL_XBRL_CACHE_DIR"),
        l2_enabled=_env_flag("FUNDAMENTAL_XBRL_CACHE_L2_ENABLED", default=False),
        l3_enabled=_env_flag("FUNDAMENTAL_XBRL_CACHE_L3_ENABLED", default=True),
    )


def _build_redis_client(redis_url: str) -> _RedisClientLike | None:
    try:
        if importlib.util.find_spec("redis") is None:
            return None
        redis_module = importlib.import_module("redis")
        redis_cls = getattr(redis_module, "Redis", None)
        if redis_cls is None:
            return None
        client = redis_cls.from_url(redis_url, decode_responses=True)
        if not isinstance(client, object):
            return None
        ping_fn = getattr(client, "ping", None)
        if callable(ping_fn):
            ping_fn()
        return cast(_RedisClientLike, client)
    except Exception:
        return None


def _as_json_object(value: object) -> JSONObject | None:
    if not isinstance(value, dict):
        return None
    parsed: JSONObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        parsed[key] = cast(JSONValue, item)
    return parsed


def _stable_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_arelle_taxonomy_cache_token(
    *,
    taxonomy_version: object,
    validation_mode: object,
    disclosure_system: object,
    plugins: Sequence[object] | None,
    packages: Sequence[object] | None,
    arelle_version: object,
) -> str:
    base_token = _normalize_cache_token(taxonomy_version)
    mode_token = _normalize_cache_token(validation_mode)
    disclosure_token = _normalize_cache_token(disclosure_system)
    version_token = _normalize_cache_token(arelle_version)
    plugin_tokens = _normalize_sequence_tokens(plugins)
    package_tokens = _normalize_sequence_tokens(packages)
    if (
        mode_token == _UNKNOWN_CACHE_TOKEN
        and disclosure_token == _UNKNOWN_CACHE_TOKEN
        and version_token == _UNKNOWN_CACHE_TOKEN
        and not plugin_tokens
        and not package_tokens
    ):
        return base_token

    fingerprint_source = "|".join(
        (
            base_token,
            mode_token,
            disclosure_token,
            version_token,
            ",".join(plugin_tokens),
            ",".join(package_tokens),
        )
    )
    digest = _stable_key_hash(fingerprint_source)[:12]
    return f"{base_token}__{mode_token}__{disclosure_token}__{version_token}__{digest}"


def _normalize_sequence_tokens(values: Sequence[object] | None) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        return ()
    tokens = {
        _normalize_cache_token(value)
        for value in values
        if _normalize_cache_token(value) != _UNKNOWN_CACHE_TOKEN
    }
    return tuple(sorted(tokens))


def _normalize_cache_token(value: object) -> str:
    if not isinstance(value, str):
        return _UNKNOWN_CACHE_TOKEN
    normalized = value.strip().lower()
    if not normalized:
        return _UNKNOWN_CACHE_TOKEN
    safe = re.sub(r"[^a-z0-9._-]+", "_", normalized)
    return safe.strip("_") or _UNKNOWN_CACHE_TOKEN


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if not isinstance(raw, str):
        return default
    token = raw.strip().lower()
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return default
