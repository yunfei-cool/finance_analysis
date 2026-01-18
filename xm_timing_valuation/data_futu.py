import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from futu import OpenQuoteContext, RET_OK

logger = logging.getLogger(__name__)


@dataclass
class FutuConfig:
    host: str
    port: int
    max_retry: int
    retry_sleep: float
    cache_dir: str


class FutuDataClient:
    """Wrapper around futu OpenQuoteContext with caching and retries."""

    def __init__(self, config: FutuConfig) -> None:
        self.config = config
        self.quote_ctx = OpenQuoteContext(host=config.host, port=config.port)
        os.makedirs(config.cache_dir, exist_ok=True)

    def close(self) -> None:
        self.quote_ctx.close()

    def _cache_path(self, key: str) -> str:
        safe_key = key.replace("/", "_")
        return os.path.join(self.config.cache_dir, f"{safe_key}.json")

    def _read_cache(self, key: str) -> Optional[Dict]:
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed reading cache %s: %s", path, exc)
            return None

    def _write_cache(self, key: str, payload: Dict) -> None:
        path = self._cache_path(key)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("Failed writing cache %s: %s", path, exc)

    def _request_with_retry(self, func, *args, **kwargs):
        last_err = None
        for attempt in range(self.config.max_retry + 1):
            ret_code, data = func(*args, **kwargs)
            if ret_code == RET_OK:
                return data
            last_err = data
            logger.warning("OpenAPI request failed (%s/%s): %s", attempt + 1, self.config.max_retry + 1, data)
            time.sleep(self.config.retry_sleep)
        raise RuntimeError(f"OpenAPI request failed after retries: {last_err}")

    def get_snapshot(self, codes: Iterable[str]) -> pd.DataFrame:
        codes_list = list(codes)
        cache_key = f"snapshot_{'_'.join(codes_list)}"
        cached = self._read_cache(cache_key)
        if cached:
            logger.info("Loaded snapshot from cache for %s", codes_list)
            return pd.DataFrame(cached)
        data = self._request_with_retry(self.quote_ctx.get_market_snapshot, codes_list)
        payload = data.to_dict(orient="records")
        self._write_cache(cache_key, payload)
        return data

    def get_kline(self, code: str, days: int) -> pd.DataFrame:
        cache_key = f"kline_{code}_{days}"
        cached = self._read_cache(cache_key)
        if cached:
            logger.info("Loaded kline cache for %s", code)
            return pd.DataFrame(cached)
        data = self._request_with_retry(
            self.quote_ctx.get_history_kline,
            code,
            start=None,
            end=None,
            ktype="K_DAY",
            autype="qfq",
            max_count=days,
        )
        payload = data.to_dict(orient="records")
        self._write_cache(cache_key, payload)
        return data

    def get_option_chain(self, code: str) -> Optional[pd.DataFrame]:
        try:
            data = self._request_with_retry(self.quote_ctx.get_option_chain, code)
        except Exception as exc:
            logger.warning("Option chain not available for %s: %s", code, exc)
            return None
        return data


def normalize_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Normalize snapshot columns for downstream usage."""
    rename_map = {
        "code": "code",
        "last_price": "price",
        "price": "price",
        "prev_close": "pre_close",
        "close": "close",
        "turnover": "turnover",
        "volume": "volume",
        "pe_ttm": "pe_ttm",
        "pb": "pb",
        "market_cap": "market_cap",
    }
    columns = {col: rename_map[col] for col in snapshot.columns if col in rename_map}
    snapshot = snapshot.rename(columns=columns)
    return snapshot


def extract_snapshot_fields(snapshot: pd.DataFrame, code: str) -> Dict[str, Optional[float]]:
    """Extract relevant fields from snapshot row."""
    row = snapshot.loc[snapshot["code"] == code]
    if row.empty:
        raise ValueError(f"Snapshot missing code {code}")
    data = row.iloc[0].to_dict()
    return {
        "price": data.get("price"),
        "close": data.get("close") or data.get("price"),
        "pre_close": data.get("pre_close"),
        "market_cap": data.get("market_cap"),
        "pe_ttm": data.get("pe_ttm"),
        "pb": data.get("pb"),
        "turnover": data.get("turnover"),
        "volume": data.get("volume"),
    }
