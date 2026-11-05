"""Live mining data: WhatToMine's CPU coin feed plus the Bitcoin price from CoinGecko, cached on disk."""
from __future__ import annotations

import json
import threading
import time
import urllib.request

from . import __version__, store

USER_AGENT = f"MINTRO/{__version__}"
WTM_URL = "https://whattomine.com/cpu.json"
BTC_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies={}"
TTL = 600  # seconds; network stats don't move faster than this in a useful way

_lock = threading.Lock()


def fetch_json(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(currency: str, force: bool = False) -> dict:
    """{fetched, coins, btc: {currency: price}, stale}. Falls back to the last saved data when offline."""
    cur = currency.lower()
    with _lock:
        cache = store.load("market.json") or {}
        fresh = time.time() - cache.get("fetched", 0) < TTL and cur in cache.get("btc", {})
        if fresh and not force:
            return {**cache, "stale": False}
        try:
            coins = fetch_json(WTM_URL)["coins"]
            btc = fetch_json(BTC_URL.format(",".join(sorted({cur, "usd"}))))["bitcoin"]
        except Exception as e:
            if cache.get("coins"):
                return {**cache, "stale": True, "error": f"{type(e).__name__}: {e}"}
            raise RuntimeError("Can't reach the live price feeds and there's no saved data yet. "
                               "Check your internet connection.") from e
        cache = {"fetched": time.time(), "coins": coins, "btc": btc}
        store.save("market.json", cache)
        return {**cache, "stale": False}
