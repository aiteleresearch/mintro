"""Sponsored coins and affiliate links.

Sponsored coins are promo listings (listings.py) for coins MINTRO can't mine yet. They are always labelled
"Sponsored" and shown apart from the basket. Affiliate links carry the publisher's referral code only when one
is set in config.py, and are then labelled as affiliate links.
"""
from __future__ import annotations

from . import config, listings


def sponsored(coins: dict) -> list[dict]:
    """Promo listings (coins not mineable with MINTRO yet), for the Sponsored box."""
    return listings.promos(coins)


def market_links(coin: dict) -> list[dict]:
    """Where a listed coin trades, with the publisher's referral code where one is configured."""
    out = []
    for m in coin.get("markets") or []:
        ref = config.EXCHANGE_REFERRALS.get(m["name"], "")
        url = m["url"] + (("&" if "?" in m["url"] else "?") + ref if ref else "")
        out.append({"name": m["name"], "url": url, "affiliate": bool(ref)})
    return out


def hardware_wallets(symbol: str) -> list[dict]:
    return [{"name": name, "url": w["ref"] or w["url"], "affiliate": bool(w["ref"])}
            for name, w in config.HARDWARE_WALLETS.items() if symbol in w.get("coins", [])]
