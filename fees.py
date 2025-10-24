"""
fees.py
Unified fee retriever for:
  • Kraken (REST v1 private /0/private/TradeVolume, HMAC-SHA512)
  • Coinbase Advanced (REST v3 /api/v3/brokerage/transaction_summary, ECDSA)

Design:
  - Async (aiohttp)
  - 1-hour in-memory cache (per (exchange, product/pair))
  - Conservative defaults if auth is missing or a call fails
  - Reads creds via auth_* modules that pull from environment

Expected env (loaded elsewhere via python-dotenv):
  # Kraken
  KRAKEN_API_KEY=...
  KRAKEN_API_SECRET_B64=...

  # Coinbase Advanced (choose inline key or path)
  CB_ADV_API_KEY=organizations/.../apiKeys/<id>
  CB_ADV_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----\n"
  # or
  # CB_ADV_PRIVATE_KEY_PATH=~/.keys/coinbase_private.pem
"""

from __future__ import annotations
import time
from typing import Dict, Tuple, Optional

import aiohttp

from auth_kraken import KrakenAuth
from auth_coinbase import CoinbaseAdvAuth

# ----------------------------------------------------------------------
# Conservative fallbacks (adjust to current public schedules if needed)
# ----------------------------------------------------------------------
DEFAULT_FEES = {
    "kraken":   {"taker": 0.0026, "maker": 0.0016},  # 26 / 16 bps
    "coinbase": {"taker": 0.0060, "maker": 0.0040},  # 60 / 40 bps
}
CACHE_TTL = 3600  # seconds


class FeeCache:
    """
    Async fee retriever with simple in-memory TTL cache.

    Usage:
        cache = FeeCache()
        kr = await cache.get_fees("kraken", "BTC/USD")
        cb = await cache.get_fees("coinbase", "BTC-USD")
    """

    def __init__(self, ttl_seconds: int = CACHE_TTL):
        self.ttl = ttl_seconds
        self._cache: Dict[Tuple[str, str], Tuple[dict, float]] = {}

    # --------------- cache helpers ----------------
    def _get_cached(self, key: Tuple[str, str]) -> Optional[dict]:
        hit = self._cache.get(key)
        if not hit:
            return None
        data, ts = hit
        if time.time() - ts < self.ttl:
            return data
        return None

    def _set_cached(self, key: Tuple[str, str], fees: dict) -> None:
        self._cache[key] = (fees, time.time())

    # --------------- public API -------------------
    async def get_fees(self, exchange: str, product_or_pair: str) -> dict:
        """
        exchange: "kraken" or "coinbase"
        product_or_pair:
          - Kraken  : "BTC/USD" (pair)
          - Coinbase: "BTC-USD" (product)
        """
        ex = exchange.lower()
        key = (ex, product_or_pair)
        cached = self._get_cached(key)
        if cached:
            return cached

        if ex == "kraken":
            fees = await self._kraken_fees(product_or_pair)
        elif ex == "coinbase":
            fees = await self._coinbase_adv_fees()
        else:
            raise ValueError(f"Unknown exchange '{exchange}'")

        self._set_cached(key, fees)
        return fees

    # --------------- exch impls -------------------
    async def _kraken_fees(self, pair: str) -> dict:
        """
        Kraken: /0/private/TradeVolume (POST, urlencoded)
        - taker fee in result['fees'][pair]['fee'] (percent)
        - maker fee in result['fees_maker'][pair]['fee'] (percent, may be absent)
        """
        try:
            auth = KrakenAuth.from_env()
        except Exception as e:
            print(f"[KRAKEN_WARN] {e} — using defaults")
            return DEFAULT_FEES["kraken"]

        url, headers, body_str = auth.trade_volume(pair)

        async with aiohttp.ClientSession() as sess:
            try:
                async with sess.post(url, data=body_str, headers=headers, timeout=8) as r:
                    js = await r.json()
            except Exception as e:
                print(f"[KRAKEN_ERR] HTTP: {e} — using defaults")
                return DEFAULT_FEES["kraken"]

        if js.get("error"):
            print(f"[KRAKEN_ERR] {js['error']} — using defaults")
            return DEFAULT_FEES["kraken"]

        res = js.get("result", {})
        taker_pct = None
        maker_pct = None
        try:
            taker_pct = float(res.get("fees", {}).get(pair, {}).get("fee"))
        except Exception:
            pass
        try:
            maker_pct = float(res.get("fees_maker", {}).get(pair, {}).get("fee"))
        except Exception:
            pass

        taker = (taker_pct / 100.0) if taker_pct is not None else DEFAULT_FEES["kraken"]["taker"]
        maker = (maker_pct / 100.0) if maker_pct is not None else DEFAULT_FEES["kraken"]["maker"]
        return {"taker": taker, "maker": maker}

    async def _coinbase_adv_fees(self) -> dict:
        """
        Coinbase Advanced: /api/v3/brokerage/transaction_summary (GET, JSON)
        - fee_tier.taker_fee_rate
        - fee_tier.maker_fee_rate
        """
        try:
            auth = CoinbaseAdvAuth.from_env()
        except Exception as e:
            print(f"[CB_ADV_WARN] {e} — using defaults")
            return DEFAULT_FEES["coinbase"]

        path = "/api/v3/brokerage/transaction_summary"
        url = auth.api_url(path)
        headers = auth.sign("GET", path)

        async with aiohttp.ClientSession() as sess:
            try:
                async with sess.get(url, headers=headers, timeout=8) as r:
                    js = await r.json()
            except Exception as e:
                print(f"[CB_ADV_ERR] HTTP: {e} — using defaults")
                return DEFAULT_FEES["coinbase"]

        tier = js.get("fee_tier")
        if not isinstance(tier, dict):
            print(f"[CB_ADV_WARN] unexpected payload: {js} — using defaults")
            return DEFAULT_FEES["coinbase"]

        try:
            taker = float(tier.get("taker_fee_rate", DEFAULT_FEES["coinbase"]["taker"]))
            maker = float(tier.get("maker_fee_rate", DEFAULT_FEES["coinbase"]["maker"]))
            return {"taker": taker, "maker": maker}
        except Exception as e:
            print(f"[CB_ADV_ERR] parse fail: {e} — using defaults")
            return DEFAULT_FEES["coinbase"]


# -------------------------- manual smoke test ----------------------------
if __name__ == "__main__":
    import asyncio

    async def main():
        cache = FeeCache()
        kr = await cache.get_fees("kraken", "BTC/USD")
        cb = await cache.get_fees("coinbase", "BTC-USD")
        print("Kraken fees  :", kr)
        print("Coinbase fees:", cb)

    asyncio.run(main())


