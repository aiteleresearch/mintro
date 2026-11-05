"""Coin listings: coins whose projects applied (and paid) to be listed in MINTRO, published by the MINTRO admin.

The admin keeps listings/listings.json in the GitHub repository and signs it (publisher/admin.py does both).
Every installed copy checks it every 10 minutes (a conditional request: an unchanged feed costs one tiny reply),
verifies the signature against the publisher key, and merges it into the coin list. When the serial number
goes up, the app replans straight away, so a coin the admin lists reaches every running MINTRO within about
15 minutes of publishing, with no app update. A feed with a lower serial number than one already seen is
ignored, so an old feed can't be replayed.

Feed: {"serial": 12, "issued": "2026-11-05T10:00:00Z", "coins": [listing, ...]}
Listing:
  symbol, name, status ("listed" | "paused" | "delisted"), tier ("standard" | "featured" | "promo"),
  until ("YYYY-MM-DD", optional), pitch (one sentence), min_share (featured: guaranteed share of mining time)
  source "rplant": the coin is on the rplant pool, which supplies its network data, or
  source "custom": algo (an algorithm MINTRO mines, as rplant names it), pools [{name, host, port, tls, user?}],
                   network {hashrate, block_time, reward, min_payout, fee, price_usd, miners},
                   network_api (optional URL returning those network fields as JSON, read by the app)
  links {site, wallet, be}, markets [{name, url}]

What people are told, and what this module enforces:
- Listed coins carry a "Listed" label and are scored like every other coin: a listing buys a place in the
  catalog, not a better score.
- Featured coins also get a guaranteed share of mining time, at most MAX_FEATURED_SHARE, labelled with that
  share. Settings > "Featured listings" turns the guarantees off on that PC.
- Promo listings aren't mined: they appear in the Sponsored box (a coin MINTRO can't mine yet).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import time

from . import config, market, signing, store

log = logging.getLogger("mintro.listings")

TTL = 600  # how often to look for a new feed
NETWORK_TTL = 900
MAX_FEATURED_SHARE = 0.10
_lock = threading.Lock()
_network_cache: dict = {}


def signed_message(serial: int, sha256: str) -> bytes:
    return f"MINTRO listings {serial} {sha256}".encode()


def verify(raw: bytes, sig: dict) -> bool:
    try:
        digest = hashlib.sha256(raw).hexdigest()
        serial = int(json.loads(raw)["serial"])
        signature = base64.urlsafe_b64decode(sig["signature"] + "=" * (-len(sig["signature"]) % 4))
        return (sig.get("sha256") == digest and int(sig.get("serial", -1)) == serial
                and signing.verify(bytes.fromhex(signing.PUBLIC_KEY_HEX), signed_message(serial, digest), signature))
    except Exception:
        return False


def feed_url() -> str:
    prefs = store.load("app-prefs.json") or {}
    if prefs.get("listings_feed"):  # a staging feed, e.g. while the admin checks a change before publishing
        return prefs["listings_feed"]
    if config.LISTINGS_URL:
        return config.LISTINGS_URL
    return f"https://raw.githubusercontent.com/{config.GITHUB_REPO}/main/listings/listings.json" if config.GITHUB_REPO else ""


def feed(force: bool = False) -> dict:
    """The current verified feed ({"serial", "coins": [...]}); the last good copy when offline."""
    with _lock:
        cache = store.load("listings.json") or {}
        url = feed_url()
        if url and (force or time.time() - cache.get("checked", 0) > TTL):
            cache["checked"] = time.time()
            try:
                same_source = cache.get("url") == url and cache.get("feed")
                raw, etag = _get(url, 2 * 1024 * 1024, cache.get("etag") if same_source else None)
                if raw is None:  # 304: unchanged since last time
                    store.save("listings.json", cache)
                    return cache["feed"]
                sig = json.loads(_get(url + ".sig", 16 * 1024)[0])
                if not verify(raw, sig):
                    raise ValueError("signature doesn't match the publisher key")
                data = json.loads(raw)
                if int(data["serial"]) < int((cache.get("feed") or {}).get("serial", 0)):
                    raise ValueError(f"serial {data['serial']} is older than the one already in use")
                cache.update(feed=data, etag=etag, url=url)
                log.info("coin listings: serial %s, %d entries", data["serial"], len(data.get("coins", [])))
            except Exception as e:
                log.warning("coin listings not updated: %s", e)
            store.save("listings.json", cache)
        return cache.get("feed") or {"serial": 0, "coins": []}


def serial() -> int:
    """Serial of the feed in use (0 if none); checks for a newer one when it's time to."""
    return int(feed().get("serial", 0))


def current(tiers: tuple = ("standard", "featured")) -> list[dict]:
    today = time.strftime("%Y-%m-%d")
    return [c for c in feed().get("coins", []) if isinstance(c, dict) and c.get("symbol")
            and c.get("status", "listed") == "listed" and (c.get("until") or "9999") >= today
            and c.get("tier", "standard") in tiers]


def apply(coins: dict, engines: dict) -> dict:
    """Merge listed coins into the coin list (a new dict; the input isn't changed)."""
    out = dict(coins)
    for item in current():
        sym = str(item["symbol"]).upper()
        tier = item.get("tier", "standard")
        meta = {"tier": tier, "pitch": str(item.get("pitch") or "")[:200], "until": item.get("until"),
                "min_share": min(max(float(item.get("min_share") or 0), 0), MAX_FEATURED_SHARE) if tier == "featured" else 0.0}
        if item.get("source", "rplant") == "rplant":
            if sym not in out:
                continue  # not (or no longer) on the pool: nothing to mine
            coin = {**out[sym], "listing": meta}
        else:
            coin = _custom(item, sym, engines)
            if not coin:
                continue
            coin["listing"] = meta
        coin["links"] = {**{k: v for k, v in (item.get("links") or {}).items() if _https(v)}, **coin.get("links", {})}
        out[sym] = coin
    return out


def promos(mineable: dict) -> list[dict]:
    """Promo listings for the Sponsored box."""
    return [{"symbol": str(c["symbol"]).upper()[:10], "name": str(c.get("name") or c["symbol"])[:40],
             "pitch": str(c.get("pitch") or "")[:200], "until": c.get("until"),
             "links": {k: v for k, v in (c.get("links") or {}).items() if k in ("site", "wallet", "be") and _https(v)},
             "mineable": str(c["symbol"]).upper() in mineable}
            for c in current(("promo",))]


def _custom(item: dict, sym: str, engines: dict) -> dict | None:
    engine = engines.get(item.get("algo"))
    pools = [{"name": str(p.get("name") or p["host"])[:40], "host": str(p["host"]), "port": int(p["port"]),
              "tls": bool(p.get("tls")), "user": str(p.get("user") or "{address}")}
             for p in item.get("pools") or [] if isinstance(p, dict) and p.get("host") and p.get("port")]
    net = {**(item.get("network") or {}), **_network_api(item.get("network_api"), sym)}
    try:
        hashrate, block_time, reward = float(net["hashrate"]), float(net["block_time"]), float(net["reward"])
    except (KeyError, TypeError, ValueError):
        return None
    if not engine or not pools or hashrate <= 0 or block_time <= 0 or reward <= 0:
        return None
    markets = [m for m in item.get("markets") or [] if isinstance(m, dict) and m.get("name") and _https(m.get("url"))]
    price = net.get("price_usd")
    return {
        "symbol": sym, "id": sym.lower(), "name": str(item.get("name") or sym)[:40],
        "engine": engine[0], "algo": engine[1], "family": engine[2], "lane": engine[3],
        "block_time": block_time, "reward": reward, "net_hps": hashrate, "pool_hps": 0.0,
        "miners": int(net.get("miners") or 0), "height": 0,
        "min_payout": float(net.get("min_payout") or 0), "fee": float(net.get("fee") or 0),
        "price_usd": float(price) if price else None, "change24": None,
        "exchanges": [m["name"] for m in markets], "markets": markets,
        "pools": pools, "port": pools[0]["port"], "tls": pools[0]["tls"], "regions": [], "links": {},
    }


def _network_api(url, sym: str) -> dict:
    """Live network numbers from the coin's own API, if the listing has one (cached; failures are ignored)."""
    if not _https(url):
        return {}
    hit = _network_cache.get(sym)
    if hit and time.time() - hit[0] < NETWORK_TTL:
        return hit[1]
    try:
        data = market.fetch_json(url, timeout=10)
        data = {k: data[k] for k in ("hashrate", "block_time", "reward", "min_payout", "fee", "price_usd", "miners") if k in data}
    except Exception:
        data = {}
    _network_cache[sym] = (time.time(), data)
    return data


def _https(url) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _get(url: str, limit: int, etag: str | None = None) -> tuple[bytes | None, str | None]:
    """(body, ETag), or (None, etag) when the server says it hasn't changed (HTTP 304)."""
    import urllib.error
    import urllib.request
    headers = {"User-Agent": market.USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            data, new_etag = r.read(limit + 1), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag
        raise
    if len(data) > limit:
        raise ValueError("feed is larger than expected")
    return data, new_etag
