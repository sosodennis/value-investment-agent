from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class CacheResult:
    data: pd.DataFrame | pd.Series | None
    cache_hit: bool
    cache_age_seconds: float | None
    cache_bucket: str | None


class MarketDataCache:
    def __init__(self, base_dir: str | None = None) -> None:
        root = Path(base_dir or "/tmp/ta_market_data_cache")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root

    def get(
        self,
        *,
        key: str,
        max_age_seconds: float,
        cache_bucket: str | None,
    ) -> CacheResult:
        payload_path = self._root / f"{key}.pkl"
        meta_path = self._root / f"{key}.json"
        if not payload_path.exists() or not meta_path.exists():
            return CacheResult(
                data=None,
                cache_hit=False,
                cache_age_seconds=None,
                cache_bucket=cache_bucket,
            )

        try:
            meta = json.loads(meta_path.read_text())
            created_at = float(meta.get("created_at", 0))
        except Exception:
            return CacheResult(
                data=None,
                cache_hit=False,
                cache_age_seconds=None,
                cache_bucket=cache_bucket,
            )

        age = time.time() - created_at
        if age > max_age_seconds:
            return CacheResult(
                data=None,
                cache_hit=False,
                cache_age_seconds=age,
                cache_bucket=cache_bucket,
            )

        try:
            data = pd.read_pickle(payload_path)
        except Exception:
            return CacheResult(
                data=None,
                cache_hit=False,
                cache_age_seconds=age,
                cache_bucket=cache_bucket,
            )

        return CacheResult(
            data=data,
            cache_hit=True,
            cache_age_seconds=age,
            cache_bucket=cache_bucket,
        )

    def set(self, *, key: str, data: pd.DataFrame | pd.Series) -> None:
        payload_path = self._root / f"{key}.pkl"
        meta_path = self._root / f"{key}.json"
        data.to_pickle(payload_path)
        meta_path.write_text(json.dumps({"created_at": time.time()}))
