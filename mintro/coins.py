"""The coin universe: coins on the rplant pool that one of MINTRO's engines can mine, plus listed coins.

rplant publishes everything a basket needs in two public feeds: /api/dash (ports, block time, price,
exchanges, links) and /api/currencies (reward, network hashrate, minimum payout, fee). Coins listed by the
MINTRO admin (listings.py) are merged in on top, including coins on their own pools.
"""
from __future__ import annotations

import base64
import json
import re
import socket
import threading
import time

from . import market, store

DASH_URL = "https://pool.rplant.xyz/api/dash"
CURRENCIES_URL = "https://pool.rplant.xyz/api/currencies"
POOL_HOST = "stratum-{region}.rplant.xyz"
TTL = 900
REGION_TTL = 86400
CACHE_VERSION = 5

# Official wallet pages where a coin has one; otherwise its GitHub releases page is where the wallet ships
WALLET_PAGES = {"XMR": "https://www.getmonero.org/downloads/", "BMR": "https://bitmonero.io/"}

# rplant algorithm -> (engine, the engine's name for it, speed family, lane, the miner rplant must list for it)
ENGINES = {
    "RandomX": ("xmrig", "rx/0", "rx", "cpu", "xmrig"),
    "RandomARQ": ("xmrig", "rx/arq", "rx", "cpu", "xmrig"),
    "RandomWOW": ("xmrig", "rx/wow", "rx", "cpu", "xmrig"),
    "gr": ("xmrig", "gr", "gr", "cpu", "xmrig"),
    "yespower": ("cpuminer", "yespower", "yespower", "cpu", "cpu"),
    "yespowerR16": ("cpuminer", "yespowerr16", "yespower", "cpu", "cpu"),
    "yescryptR32": ("cpuminer", "yescryptr32", "yescrypt", "cpu", "cpu"),
    "power2b": ("cpuminer", "power2b", "power2b", "cpu", "cpu"),
    "minotaurx": ("cpuminer", "minotaurx", "minotaurx", "cpu", "cpu"),
    "firopow": ("srbminer", "firopow", "progpow", "gpu", "srbminer-multi"),
    "meowpow": ("srbminer", "meowpow", "progpow", "gpu", "srbminer-multi"),
}

_lock = threading.Lock()


def get(force: bool = False) -> dict:
    """{fetched, coins: {SYMBOL: coin}, stale}: rplant's coins with the current listings merged in."""
    from . import listings
    try:
        data = _rplant(force)
    except RuntimeError as e:
        data = {"coins": {}, "stale": True, "error": str(e)}
    merged = listings.apply(data["coins"], ENGINES)
    if not merged and data.get("error"):
        raise RuntimeError(data["error"])
    return {**data, "coins": merged}


def _rplant(force: bool) -> dict:
    """rplant's coins. Falls back to the last saved list when offline."""
    with _lock:
        cache = store.load("coins.json") or {}
        if cache.get("version") != CACHE_VERSION:
            cache = {}
        if not force and time.time() - cache.get("fetched", 0) < TTL and cache.get("coins"):
            return {**cache, "stale": False}
        try:
            dash = market.fetch_json(DASH_URL, timeout=30)
            currencies = market.fetch_json(CURRENCIES_URL, timeout=30)
        except Exception as e:
            if cache.get("coins"):
                return {**cache, "stale": True, "error": f"{type(e).__name__}: {e}"}
            raise RuntimeError("Can't reach the rplant pool to list coins. Check your internet connection.") from e
        coins, tbs = {}, dash.get("tbs") or {}
        # Coins mined on two algorithms (e.g. Avian) split their blocks between them; skip rather than miscount
        seen: dict = {}
        for entry in tbs.values():
            info = entry.get("info") or {}
            seen.setdefault(info.get("symbol"), set()).add(info.get("algorithm"))
        for key, entry in tbs.items():
            coin = _parse(key, entry, currencies)
            if coin and len(seen.get(coin["symbol"], ())) == 1:
                coins[coin["symbol"]] = coin
        cache = {"version": CACHE_VERSION, "fetched": time.time(), "coins": coins}
        store.save("coins.json", cache)
        return {**cache, "stale": False}


def _parse(key: str, entry: dict, currencies: dict) -> dict | None:
    info = entry.get("info") or {}
    engine = ENGINES.get(info.get("algorithm"))
    symbol = info.get("symbol")
    stats = currencies.get(symbol) or {}
    if not engine or not symbol or engine[4] not in _miners(info):
        return None
    links = info.get("links") or {}
    net_hps = float(entry.get("hrN") or stats.get("network_hashrate") or 0)
    reward = float(stats.get("reward") or 0)
    block_time = float(links.get("btime") or 0)
    port = _best_port(info.get("ports") or {})
    if net_hps <= 0 or reward <= 0 or block_time <= 0 or not port:
        return None
    price = info.get("price")
    return {
        "symbol": symbol,
        "id": key,
        "name": _title(info.get("namelong") or key),
        "engine": engine[0],
        "algo": engine[1],
        "family": engine[2],
        "lane": engine[3],
        "block_time": block_time,
        "reward": reward,
        "net_hps": net_hps,
        "pool_hps": float(entry.get("hr") or 0),
        "miners": int(entry.get("mc") or 0),
        "height": int(entry.get("bN") or 0),
        "min_payout": float(stats.get("minimumPayment") or info.get("minimumPayment") or 0),
        "fee": float(str(stats.get("fee", 1)).rstrip("%") or 1) / 100,
        "price_usd": float(price) if price else None,
        "change24": _change24(entry.get("marketStats")),
        "exchanges": [name for ex in links.get("exs") or [] for name in ex],
        "markets": [{"name": name, "url": url} for ex in links.get("exs") or [] if isinstance(ex, dict)
                    for name, url in ex.items() if isinstance(url, str) and url.startswith("https://")],
        "port": port[0],
        "tls": port[1],
        "regions": links.get("stratums") or ["eu", "na", "asia", "ru"],
        "links": {k: v for k, v in (("site", links.get("site")), ("wallet", _wallet_page(symbol, links.get("github"))),
                                    ("be", links.get("be"))) if isinstance(v, str) and v.startswith("https://")},
    }


def _wallet_page(symbol: str, github) -> str | None:
    if symbol in WALLET_PAGES:
        return WALLET_PAGES[symbol]
    m = re.match(r"https://github\.com/([\w.-]+)/([\w.-]+)", github or "")
    return f"https://github.com/{m[1]}/{m[2]}/releases" if m else None


def _miners(info: dict) -> set:
    names = set()
    for k in (info.get("mm") or {}):
        try:
            names.add(base64.b64decode(k).decode().lower())
        except ValueError:
            pass
    return names


def _best_port(ports: dict) -> tuple[int, bool] | None:
    """Lowest-difficulty port (CPU miners want frequent shares), preferring encrypted TLS."""
    options = [(not v.get("tls"), float(v.get("diff") or 0), int(p)) for p, v in ports.items()
               if p.isdigit() and int(p) != 9997 and not v.get("solo")]
    if not options:
        return None
    plain_first, _, port = min(options)
    return port, not plain_first


def _change24(stats) -> float | None:
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except ValueError:
            return None
    value = (stats or {}).get("usd_24h_change") if isinstance(stats, dict) else None
    return round(float(value), 1) if value is not None else None


def _title(name: str) -> str:
    return name if any(c.isupper() for c in name) else name.title()


def best_region(coin: dict) -> str:
    """Nearest rplant server, by TCP connect time. Measured once a day."""
    saved = store.load("region.json") or {}
    if time.time() - saved.get("at", 0) < REGION_TTL and saved.get("region") in coin["regions"]:
        return saved["region"]
    timings = {}
    for region in coin["regions"]:
        start = time.perf_counter()
        try:
            with socket.create_connection((POOL_HOST.format(region=region), coin["port"]), timeout=3):
                timings[region] = time.perf_counter() - start
        except OSError:
            continue
    region = min(timings, key=timings.get) if timings else coin["regions"][0]
    store.save("region.json", {"region": region, "at": time.time(), "ms": {r: round(t * 1000) for r, t in timings.items()}})
    return region
