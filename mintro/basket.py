"""The adaptive lottery basket: which coins to mine and what share of mining time each one gets.

Total earnings are fixed by the laptop's speed; the basket only spreads that speed across several
speculative bets. It holds as many coins as can each reach the pool's minimum payout within
PAYOUT_DAYS, so nothing mined gets stranded on the pool.
"""
from __future__ import annotations

import math
import re

PAYOUT_DAYS = 7
MAX_COINS = 500  # the ceiling; the real size adapts to what this laptop's speed can carry

ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{26,200}$|^[a-z0-9]{1,10}1[02-9ac-hj-np-z]{20,100}$")


def valid_address(address: str) -> bool:
    """Format check only (base58 or bech32). The pool has the final word when MINTRO logs in."""
    return bool(ADDRESS.match(address.strip()))


def plan(coins: dict, speeds: dict, wallets: dict, rejected: set, max_coins: int = MAX_COINS,
         featured: bool = True) -> dict:
    """{"entries": [...], "active": [symbols]} with each entry's score, reason, share and status.

    Listed coins are scored like any other. A featured listing (if `featured` is on) is placed first and gets
    at least its guaranteed share of mining time, provided it can reach a payout at all.
    """
    entries = []
    for symbol, coin in coins.items():
        hps = speeds.get(coin["algo"]) or 0
        share_of_net = _share_of_network(coin, hps)
        full_day = share_of_net * 86400 / coin["block_time"] * coin["reward"] * (1 - coin["fee"])
        min_share = coin["min_payout"] / (full_day * PAYOUT_DAYS) if full_day else math.inf
        listing = coin.get("listing")
        floor = listing["min_share"] if featured and listing and listing["tier"] == "featured" else 0.0
        scored = _score(coin, hps)
        if listing:
            scored["reason"] += (f" Featured listing: gets at least {floor:.0%} of mining time." if floor
                                 else " Listed by its project.")
        entries.append({
            "symbol": symbol,
            "name": coin["name"],
            "algo": coin["algo"],
            "hps": hps,
            "emission_share": share_of_net,
            "coins_day_full": full_day,
            "min_share": min_share,
            "price_usd": coin["price_usd"],
            "change24": coin["change24"],
            "exchanges": coin["exchanges"],
            "links": coin["links"],
            "min_payout": coin["min_payout"],
            "address": wallets.get(symbol, ""),
            "listing": listing,
            "featured_share": floor if min_share <= 1 else 0.0,
            **scored,
        })
        if entries[-1]["featured_share"]:
            entries[-1]["min_share"] = max(min_share, floor)
    entries.sort(key=lambda e: e["score"], reverse=True)

    # Which coins the basket wants (ignoring addresses), then which it can mine right now
    recommended = _fill(entries, max_coins, lambda e: True)
    active = _fill(entries, max_coins, lambda e: e["address"] and e["symbol"] not in rejected)
    _share_time(entries, active)

    for e in entries:
        if e["symbol"] in rejected:
            e["status"] = "rejected"
        elif e["min_share"] > 1:
            e["status"] = "too_slow"
            e["payout_days_full"] = e["min_payout"] / e["coins_day_full"] if e["coins_day_full"] else None
        elif e["symbol"] in active:
            e["status"] = "active"
        elif not e["address"] and e["symbol"] in recommended:
            e["status"] = "needs_address"
        else:
            e["status"] = "standby"  # basket full, or lower-ranked than what fits
        share = e.get("share", 0)
        e["payout_days"] = e["min_payout"] / (e["coins_day_full"] * share) if share and e["coins_day_full"] else None
    return {"entries": entries, "active": active, "recommended": recommended}


def _share_of_network(coin: dict, hps: float) -> float:
    """Your slice of all new coins: joining the network adds your speed to its total."""
    return hps / (coin["net_hps"] + hps) if hps else 0.0


def _score(coin: dict, hps: float) -> dict:
    """0-100: how good a lottery ticket this coin is for this laptop, plus a one-line reason."""
    share = _share_of_network(coin, hps)
    capture = min(max((math.log10(share) + 6) / 6, 0), 1) if share else 0  # 0.0001% of supply -> 0, all of it -> 1
    alive = min(coin["miners"] / 10, 1)
    early = coin["price_usd"] is None
    listed = bool(coin["price_usd"]) and bool(coin["exchanges"])
    momentum = min(max((coin["change24"] or 0) / 50 + 0.5, 0), 1) if listed else 0.5
    score = 100 * (0.45 * capture + 0.2 * alive + 0.15 * early + 0.1 * listed + 0.1 * momentum)

    pct = f"{share * 100:.2g}%" if share >= 1e-4 else "a tiny slice"
    if early:
        reason = f"You'd mine {pct} of all new {coin['symbol']}. No market yet: the earliest, riskiest stage."
    else:
        venues = ", ".join(coin["exchanges"][:2]) or "an exchange"
        reason = f"You'd mine {pct} of all new {coin['symbol']}. Tradable on {venues}."
    if coin["miners"] < 3:
        reason += " Very few miners: the coin may be abandoned."
    return {"score": round(score), "reason": reason}


def _fill(entries: list, max_coins: int, eligible) -> list:
    """Greedy by score: add coins while every chosen coin can still reach a payout in time."""
    chosen, used = [], 0.0
    for e in sorted(entries, key=lambda e: not e.get("featured_share")):  # featured first, then by score
        if len(chosen) >= max_coins:
            break
        if eligible(e) and e["min_share"] <= 1 and used + e["min_share"] <= 1:
            chosen.append(e["symbol"])
            used += e["min_share"]
    return chosen


def _share_time(entries: list, active: list) -> None:
    """Each active coin gets its payout minimum, then the spare time is split by score."""
    picked = [e for e in entries if e["symbol"] in active]
    spare = 1 - sum(e["min_share"] for e in picked)
    total_score = sum(max(e["score"], 1) for e in picked) or 1
    for e in entries:
        e["share"] = e["min_share"] + spare * max(e["score"], 1) / total_score if e in picked else 0.0
