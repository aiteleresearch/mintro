"""Pools for each coin: rplant first, then fallbacks if rplant can't be reached.

Built-in fallbacks cover well-known public pools; add your own in data\\pools.json, for example
    {"ZEPH": [{"name": "MyPool", "host": "zeph.example.com", "port": 443, "tls": true}]}
Coins mined on a fallback pool are paid by that pool, under its own minimum payout.
"""
from __future__ import annotations

from . import coins, store

FALLBACKS = {
    "XMR": [{"name": "SupportXMR", "host": "pool.supportxmr.com", "port": 443, "tls": True},
            {"name": "HashVault", "host": "pool.hashvault.pro", "port": 443, "tls": True}],
}


def options(coin: dict, address: str) -> list[dict]:
    """Every pool this coin can be mined on, in order: {name, host, port, tls, user, password}."""
    extra = (store.load("pools.json") or {}).get(coin["symbol"], []) + FALLBACKS.get(coin["symbol"], [])
    if coin.get("pools"):  # a listed coin on its own pool(s)
        own = [{**p, "user": p.get("user", "{address}").format(address=address, worker="mintro"), "password": "x"}
               for p in coin["pools"]]
        return own + [{**p, "user": address, "password": "mintro"} for p in extra
                      if isinstance(p, dict) and p.get("host") and p.get("port")]
    rplant = {"name": "rplant", "host": coins.POOL_HOST.format(region=coins.best_region(coin)), "port": coin["port"],
              "tls": coin["tls"], "user": f"{address}.mintro", "password": "x"}
    # Most public pools take the bare address as the login and the worker name as the password
    return [rplant] + [{**p, "user": address, "password": "mintro"} for p in extra
                       if isinstance(p, dict) and p.get("host") and p.get("port")]
