"""Speed, power and profit: hardware + live network data -> what mining would earn on this computer."""
from __future__ import annotations

import re
import time

from .hardware import classify

DEFAULT_FEE = 0.02  # about 1% pool fee + 1% miner dev fee

# WhatToMine algorithm name -> speed family (coins in one family hash at the same speed)
ALGO_FAMILY = {
    "RandomX": "rx", "TariRandomX": "rx", "MoneroRandomX": "rx",
    "GhostRider": "gr", "VerusHash": "verus", "Xelishashv3": "xelis",
}
DISPLAY_NAMES = {"Tari-RandomX": "Tari", "EPIC-RandomX": "Epic Cash", "Quantum R L": "QRL", "Dagger": "XDAG"}

# WhatToMine's default CPU speeds belong to a tuned Ryzen 9 7950X-class desktop.
# Every estimate is that rig's speed scaled by how this CPU compares to it.
REF_HW = {"cpu": "AMD Ryzen 9 7950X 16-Core Processor", "cores": 16, "threads": 32,
          "l3_mb": 64.0, "base_mhz": 4500, "laptop": False}
REF_HPS = {"rx": 21_000.0, "gr": 4_900.0, "verus": 55e6, "xelis": 15_200.0,
           # rough until MINTRO measures them on the PC: cpuminer-opt algorithms on the same reference rig
           "yespower": 7_000.0, "yescrypt": 9_000.0, "power2b": 2_000.0, "minotaurx": 120_000.0}
CORE_FAMILIES = [f for f in REF_HPS if f != "rx"]
REF = {**REF_HW, **classify(REF_HW)}

NO_LARGE_PAGES = 0.8  # RandomX speed without OS large pages (the Windows default)

# Typical household electricity price per kWh, used until the user types their own
DEFAULT_RATES = {"USD": 0.17, "EUR": 0.28, "GBP": 0.25, "INR": 8.0, "CAD": 0.14, "AUD": 0.32,
                 "JPY": 31.0, "CNY": 0.55, "BRL": 0.85, "CHF": 0.30}

MIN_VOLUME_USD = 20_000  # below this daily trading volume, selling what you mine is hard


def default_rate(currency: str, btc: dict) -> float:
    cur = currency.upper()
    if cur in DEFAULT_RATES:
        return DEFAULT_RATES[cur]
    local = btc.get(cur.lower())
    return float(f"{0.15 * local / btc['usd']:.3g}") if local else DEFAULT_RATES["USD"]


def _rx_score(hw: dict) -> float:
    return (hw["rx_cores"] + 0.2 * (hw["rx_threads"] - hw["rx_cores"])) * hw["rx_ghz"] * hw["arch"]


def _core_score(hw: dict) -> float:
    return (hw["cores"] + 0.25 * (hw["threads"] - hw["cores"])) * hw["allcore_ghz"] * hw["arch"]


def speeds(hw: dict, bench: dict | None = None) -> dict:
    """Hashrate and power per algorithm family: estimated, or measured/calibrated after a benchmark."""
    rx_tuned = REF_HPS["rx"] * _rx_score(hw) / _rx_score(REF)
    core_ratio = _core_score(hw) / _core_score(REF)
    full_w = hw["base_watts"] + hw["cpu_watts"]
    rx_w = hw["base_watts"] + hw["cpu_watts"] * (0.15 + 0.85 * hw["rx_cores"] / hw["cores"])

    out = {f: {"hps": REF_HPS[f] * core_ratio, "source": "estimated", "watts": full_w}
           for f in CORE_FAMILIES}
    out["rx"] = {"hps": rx_tuned * NO_LARGE_PAGES, "tuned_hps": rx_tuned, "source": "estimated", "watts": rx_w}

    if bench:
        measured = bench["rx_hps"]
        large_pages = bench.get("huge_pages_pct", 0) >= 50
        # Real speed vs the model's guess also tells us about clocks and cooling: carry it to the other algorithms
        baseline = rx_tuned if large_pages else out["rx"]["hps"]
        cal = min(max(measured / baseline, 0.5), 1.6)
        out["rx"].update(hps=measured, source="measured",
                         tuned_hps=measured if large_pages else measured / NO_LARGE_PAGES)
        for f in CORE_FAMILIES:
            out[f]["hps"] *= cal
            out[f]["source"] = "calibrated"
        if bench.get("watts"):
            scale = bench["watts"] / rx_w
            for s in out.values():
                s["watts"] *= scale
    return out


def report(hw: dict, market: dict, settings: dict, bench: dict | None, bench_status: dict) -> dict:
    btc = market["btc"]
    cur = settings["currency"].lower()
    if cur not in btc:
        cur = "usd"
    rate = float(settings["rate"])
    fee = float(settings.get("fee", DEFAULT_FEE))
    sp = speeds(hw, bench)
    coins = market["coins"]

    def part(c: dict, hps: float) -> dict:
        per_day = 86400 / float(c["block_time"]) * c["block_reward"]
        mined = hps / c["nethash"] * per_day * (1 - fee) if c.get("nethash") else 0.0
        price = c["exchange_rate"] * btc[cur]
        return {"tag": c["tag"], "coins_day": mined, "price": price, "revenue_day": mined * price}

    rows = []
    for name, c in coins.items():
        family = ALGO_FAMILY.get(c.get("algorithm"))
        if not family or c.get("tag") == "NICEHASH" or name == "Tari-Merged":
            continue
        rows.append(_row(name, c, [part(c, sp[family]["hps"])], sp[family], rate, btc["usd"]))
    # Merged mining: the same Monero work also earns Tari, so it's one option with two payouts
    if "Monero" in coins and "Tari-Merged" in coins:
        hps = sp["rx"]["hps"]
        rows.append(_row("Monero + Tari", coins["Monero"], [part(coins["Monero"], hps), part(coins["Tari-Merged"], hps)],
                         sp["rx"], rate, btc["usd"], merged=True))
    rows.sort(key=lambda r: r["profit_day"], reverse=True)
    # Recommend something you can actually sell; illiquid coins still show in the table
    best = next((r for r in rows if r["volume24_usd"] >= MIN_VOLUME_USD), rows[0] if rows else None)

    return {
        "currency": cur.upper(),
        "rate": rate,
        "fee": fee,
        "market": {"age_s": round(time.time() - market["fetched"]), "stale": market.get("stale", False)},
        "hardware": {k: hw.get(k) for k in ("cpu", "cores", "threads", "l3_mb", "ram_gb", "free_gb", "gpus",
                                            "gpu_kind", "laptop", "on_ac", "rx_threads")},
        "speeds": sp,
        "rows": rows,
        "best": best,
        "tips": _tips(hw, sp, rows, best),
        "bench": {**bench_status, "measured_at": bench["measured_at"] if bench else None},
    }


def _row(name: str, c: dict, parts: list, speed: dict, rate: float, btc_usd: float, merged: bool = False) -> dict:
    revenue = sum(p["revenue_day"] for p in parts)
    kwh = speed["watts"] * 24 / 1000
    cost = kwh * rate
    tuned_revenue = revenue * speed["tuned_hps"] / speed["hps"] if speed.get("tuned_hps") else None
    volume_usd = (c.get("exchange_rate_vol") or 0) * btc_usd
    market_cap = _usd(c.get("market_cap"))
    change = c["exchange_rate"] / c["exchange_rate24"] - 1 if c.get("exchange_rate24") else 0.0
    competition = c["difficulty"] / c["difficulty24"] - 1 if c.get("difficulty24") else 0.0

    flags = []
    if volume_usd < MIN_VOLUME_USD:
        flags.append("Hard to sell")
    if market_cap and market_cap < 5_000_000:
        flags.append("Tiny coin")
    if change <= -0.05:
        flags.append(f"Price {change:+.0%} today")
    if competition >= 0.10:
        flags.append(f"Competition {competition:+.0%} today")
    if c.get("lagging"):
        flags.append("Stale data")

    return {
        "name": DISPLAY_NAMES.get(name, name),
        "tag": "+".join(p["tag"] for p in parts),
        "algorithm": c.get("algorithm"),
        "merged": merged,
        "hps": speed["hps"],
        "speed_source": speed["source"],
        "watts": speed["watts"],
        "parts": parts,
        "revenue_day": revenue,
        "cost_day": cost,
        "profit_day": revenue - cost,
        "tuned_profit_day": tuned_revenue - cost if tuned_revenue is not None else None,
        "breakeven_rate": revenue / kwh if kwh else None,
        "change24": change,
        "volume24_usd": volume_usd,
        "market_cap_usd": market_cap,
        "flags": flags,
    }


def _tips(hw: dict, sp: dict, rows: list, best: dict | None) -> list[str]:
    tips = []
    free = hw.get("free_gb") or 0
    if 0 < free < 2.6:
        tips.append(f"Only {free:.1f} GB of your {hw.get('ram_gb', 0):.0f} GB RAM is free. RandomX coins need about "
                    f"2.5 GB, so close other apps (browser tabs especially) before mining or speed drops sharply.")
    if hw.get("laptop") and not hw.get("on_ac", True):
        tips.append("You're on battery. Mining drains it fast and heats it up, so plug in first.")
    rx = sp["rx"]
    if rx["tuned_hps"] > rx["hps"] * 1.05:
        gain = rx["tuned_hps"] / rx["hps"] - 1
        if best and best["tuned_profit_day"] is not None and best["profit_day"] <= 0 < best["tuned_profit_day"]:
            tips.append(f"Turning on large pages (a one-time Windows permission, about +{gain:.0%} speed) "
                        f"would make {best['name']} profitable.")
        else:
            tips.append(f"Turning on large pages (a one-time Windows permission) adds about {gain:.0%} RandomX speed.")
    if hw.get("gpu_kind") == "integrated":
        tips.append("Your graphics chip is built into the CPU, so it can't add speed here. MINTRO mines with the CPU.")
    return tips


def _usd(text) -> float | None:
    digits = re.sub(r"[^\d.]", "", str(text or ""))
    try:
        return float(digits) or None
    except ValueError:
        return None
