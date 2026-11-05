"""Self-test: is everything in place to mine and get paid? Read-only checks, a few seconds."""
from __future__ import annotations

import socket
import time

from . import coins, defender, miners, tuning, wallets


def run(app) -> list[dict]:
    """[{name, ok (True / False / None for information), detail}]."""
    out = []

    def check(name, ok, detail):
        out.append({"name": name, "ok": ok, "detail": detail})

    try:
        data = coins.get()
        listed = data["coins"]
        n_listed = sum(1 for c in listed.values() if c.get("listing"))
        check("Coin list", not data.get("stale"), f"{len(listed)} coins"
              + (f", {n_listed} of them listed by their projects" if n_listed else "")
              + (" (saved copy: the pool's website didn't answer)" if data.get("stale") else ""))
    except Exception as e:
        listed = {}
        check("Coin list", False, f"Couldn't load it: {e}")

    sample = next((c for c in listed.values() if c.get("regions")), None)  # an rplant coin
    if sample:
        host = coins.POOL_HOST.format(region=coins.best_region(sample))
        start = time.perf_counter()
        try:
            with socket.create_connection((host, sample["port"]), timeout=5):
                check("Pool server", True, f"{host} answered in {(time.perf_counter() - start) * 1000:.0f} ms")
        except OSError as e:
            check("Pool server", False, f"{host} didn't answer ({e.__class__.__name__}). A firewall may block it.")

    for d in miners.DRIVERS.values():
        if d.name == "srbminer" and not app.gpu_card():
            continue
        exe = d.exe()
        check(d.title, True if exe else None, "installed" if exe else "downloads automatically on the first Start")

    eng = app.engine
    if eng.defender_blocked:
        check("Windows Security", False, "it stopped the miner: use Allow MINTRO's miner on the card")
    else:
        check("Windows Security", True if defender.miner_folder_allowed() else None,
              "miner folder allowed" if defender.miner_folder_allowed() else "no block seen so far")

    with_address = [e for e in eng.plan["entries"] if e.get("address")]
    made = [s for s in wallets.SOURCES if wallets.created(s)]
    check("Wallets", bool(with_address), f"{len(with_address)} coins have an address"
          + (f"; MINTRO made wallets for {', '.join(made)}" if made else ""))

    hw = app.hardware()
    mode = tuning.memory_mode(hw)
    check("Memory", mode == "fast" or None, f"{hw.get('free_gb')} GB free: RandomX runs in {mode} mode")

    due = [e for e in eng.plan["entries"] if e.get("min_payout") and
           eng.ledger.get(e["symbol"], {}).get("coins", 0) >= e["min_payout"]]
    check("Payouts", None, ("Should have reached the pool minimum: " + ", ".join(e["symbol"] for e in due)
                            + ". Check those wallets.") if due else "No coin has reached a pool minimum yet")
    return out
