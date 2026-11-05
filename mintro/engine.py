"""Mining engine: runs one basket coin at a time and rotates turns by each coin's time share.

One coin at a time is deliberate. A laptop has one CPU cache and each RandomX miner needs ~2.5 GB of
RAM, so taking turns (weighted by the basket plan) beats running several miners side by side.
An engine runs one lane: "cpu" (XMRig, cpuminer-opt) or "gpu" (SRBMiner-Multi, for PCs with a graphics card).

The miner is a separate process writing to a log file, so it can outlive MINTRO itself: when MINTRO updates,
detach() leaves it mining and records it in a handoff file, and the new version adopts it on start.
"""
from __future__ import annotations

import collections
import ctypes
import logging
import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

from . import basket, bench, coins, defender, hardware, miners, pools, store, tuning
from .miners import CONNECT_ERROR, LOGIN_ERROR, NEW_JOB

log = logging.getLogger("mintro.engine")

SLICE_S = 20 * 60      # one coin's turn: long enough that RandomX's ~1 min warm-up is a small overhead
REPLAN_S = 30 * 60     # refresh coin data and the basket this often
TICK_S = 2
EARLY_EXIT_S = 45      # miner dying this fast without a speed reading = blocked or misconfigured
CONNECT_GRACE_S = 120  # give a pool this long to send work before skipping the coin
COOLDOWN_S = 30 * 60
LEARN_AFTER_S = 180    # trust the 60 s speed average only after warm-up
HANDOFF_MAX_AGE = 600  # a handoff older than this is stale (the update never restarted MINTRO)

POWER_MODES = ("auto", "eco", "balanced", "max")  # threads and priorities for each come from tuning.settings
GPU_TURN = {"threads": 0, "hint": 100, "cpu_threads": 1, "priority_arg": 1, "priority_class": "below_normal"}


class Engine:
    def __init__(self, estimate_speeds, hardware_info, lane: str = "cpu"):
        self.lane = lane
        self._suffix = "" if lane == "cpu" else f"-{lane}"  # each lane keeps its own ledger and speeds
        self._estimate_speeds = estimate_speeds  # () -> {algorithm or speed family: H/s}
        self._hardware = hardware_info           # () -> hardware.detect() result, kept fresh by the server
        self._driver: miners.Driver | None = None
        self._pool_index: dict = {}              # symbol -> which of pools.options() to use next
        self._memory = "fast"                    # RandomX dataset mode the plan was made for
        self._turn = {}                          # tuning.settings of the running miner
        self._priority = None                    # priority class currently applied to it
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self.want = False
        self.state, self.message = "stopped", ""
        self.current: str | None = None
        self.slice_start = 0.0
        self.hashrate = 0.0
        self.plan = {"entries": [], "active": [], "recommended": []}
        self.plan_at = 0.0
        self.coins: dict = {}
        self.prefs = {"power": "auto", "pause_on_battery": True, "max_coins": basket.MAX_COINS,
                      **(store.load("prefs.json") or {})}
        self.wallets: dict = store.load("wallets.json") or {}  # shared by both lanes: reloaded before every change
        self.rejected = set(store.load(f"rejected{self._suffix}.json") or [])
        self.ledger: dict = store.load(f"ledger{self._suffix}.json") or {}
        self.learned: dict = store.load(f"speeds{self._suffix}.json") or {}
        self.daily: dict = store.load(f"daily{self._suffix}.json") or {}  # date -> symbol -> {coins, usd, priced}
        self.cooldown: dict = {}
        self.turn_time = collections.Counter()
        self._proc: subprocess.Popen | miners.Adopted | None = None
        self._exe = ""                           # the running miner's program, for the handoff
        self._log_path, self._log_offset = store.DATA / f"miner{self._suffix}.log", 0
        self._detached = False                   # handed the miner to the next version: hands off from here on
        self._api = ("", 0, "")
        self._tail = collections.deque(maxlen=40)
        self._miner = {}  # per-process facts: started, login_failed, connected, connect_errors, got_speed, shares
        self._restart = False
        self._last_tick = self._last_save = 0.0
        self.defender_blocked = False  # Windows Security removed or stopped XMRig; don't download it into a loop
        try:
            self._adopt()
        except Exception:
            log.exception("couldn't pick up the miner from the previous version")
        threading.Thread(target=self._loop, daemon=True, name="mintro-engine").start()

    # ---- commands from the UI -------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            self.want = True
        self._wake.set()

    def stop(self) -> None:
        with self._lock:
            self.want = False
        self._wake.set()

    def clear_block(self) -> None:
        """The person allowed MINTRO's miner folder in Windows Security: try again (downloading XMRig if needed)."""
        with self._lock:
            self.defender_blocked = False
            if self.state == "blocked":
                self._set("stopped", "")
        self._wake.set()

    def set_address(self, symbol: str, address: str) -> None:
        address = address.strip()
        with self._lock:
            if symbol not in self.coins:
                raise ValueError("Unknown coin.")
            if address and not basket.valid_address(address):
                raise ValueError("That doesn't look like a wallet address. Copy it again from your wallet.")
            self.wallets = store.load("wallets.json") or {}  # the other lane may have saved an address meanwhile
            if address:
                self.wallets[symbol] = address
            else:
                self.wallets.pop(symbol, None)
            self.rejected.discard(symbol)
            store.save("wallets.json", self.wallets)
            store.save(f"rejected{self._suffix}.json", sorted(self.rejected))
            self.plan_at = 0  # replan on the next tick
        self._wake.set()

    def set_prefs(self, prefs: dict) -> None:
        with self._lock:
            if "power" in prefs:
                if prefs["power"] not in POWER_MODES:
                    raise ValueError("Unknown power mode.")
                self._restart = self._restart or prefs["power"] != self.prefs["power"]
                self.prefs["power"] = prefs["power"]
            if "pause_on_battery" in prefs:
                self.prefs["pause_on_battery"] = bool(prefs["pause_on_battery"])
            if "featured" in prefs:
                self.prefs["featured"] = bool(prefs["featured"])
                self.plan_at = 0
            if "max_coins" in prefs:
                self.prefs["max_coins"] = min(max(int(prefs["max_coins"]), 1), basket.MAX_COINS)
                self.plan_at = 0
            store.save("prefs.json", self.prefs)
        self._wake.set()

    def shutdown(self) -> None:
        with self._lock:
            if not self._detached:
                self.want = False
                self._stop_miner()
            self._save()

    # ---- updates: hand the running miner to the next version ------------------------------------

    def detach(self) -> bool:
        """Stop managing the miner but leave it mining, and record it for the next MINTRO to adopt.

        Returns True if a running miner was handed off. After this the engine does nothing until exit.
        """
        with self._lock:
            self._detached = True
            proc, self._proc = self._proc, None
            self._save()
            if not (proc and proc.poll() is None and self._driver):
                store.save(f"handoff{self._suffix}.json", {})
                return False
            store.save(f"handoff{self._suffix}.json", {
                "at": time.time(), "pid": proc.pid, "exe": self._exe, "engine": self._driver.name,
                "symbol": self.current, "slice_start": self.slice_start, "api": list(self._api), "turn": self._turn,
                "priority": self._priority, "memory": self._memory, "miner": self._miner, "hashrate": self.hashrate,
                "log": [str(self._log_path), self._log_offset], "pool_index": self._pool_index,
                "turn_time": dict(self.turn_time), "cooldown": self.cooldown, "want": self.want,
            })
            log.info("left %s mining (pid %s) for the next version", self.current, proc.pid)
            return True

    def _adopt(self) -> None:
        """Pick up the miner the previous version left running in this lane, if it's still ours and alive."""
        h = store.load(f"handoff{self._suffix}.json") or {}
        if not h.get("pid") or time.time() - h.get("at", 0) > HANDOFF_MAX_AGE:
            return
        driver = miners.DRIVERS.get(h.get("engine"))
        try:
            proc = miners.Adopted(h["pid"])
        except (OSError, AttributeError):
            return
        if (not driver or proc.poll() is not None
                or os.path.normcase(proc.image()) != os.path.normcase(h.get("exe", ""))):
            return  # gone, or the process id now belongs to something else
        self._proc, self._driver, self._exe = proc, driver, h["exe"]
        self.current, self.slice_start = h["symbol"], h["slice_start"]
        self._api, self._turn, self._priority = tuple(h["api"]), h.get("turn") or {}, h.get("priority")
        self._memory, self._miner, self.hashrate = h.get("memory", "fast"), h["miner"], h.get("hashrate", 0.0)
        self._pool_index, self.cooldown = h.get("pool_index", {}), h.get("cooldown", {})
        self.turn_time = collections.Counter(h.get("turn_time") or {})
        self._log_path, self._log_offset = Path(h["log"][0]), int(h["log"][1])
        self._last_tick = h["at"]  # the seconds it mined while MINTRO restarted count too
        self.want = h.get("want", True)
        self._set("mining" if self.hashrate else "starting", f"Mining {self.current}")
        threading.Thread(target=self._read_output, args=(proc, self._log_path, self._log_offset), daemon=True).start()
        log.info("picked up %s mining (pid %s) from the previous version", self.current, proc.pid)

    # ---- what the card shows --------------------------------------------------------------------

    def snapshot(self, fx: float, currency: str, power_watts: float, rate: float) -> dict:
        with self._lock:
            now = time.time()
            entries, total, unpriced = [], 0.0, 0
            for e in self.plan["entries"]:
                mined = self.ledger.get(e["symbol"], {}).get("coins", 0.0)
                value = mined * e["price_usd"] * fx if e["price_usd"] is not None else None
                if value is not None:
                    total += value
                elif mined:
                    unpriced += 1
                entries.append({k: e.get(k) for k in (
                    "symbol", "name", "status", "score", "reason", "share", "payout_days", "payout_days_full",
                    "min_payout", "change24", "links", "address", "exchanges", "listing", "featured_share")}
                    | {"price": e["price_usd"] * fx if e["price_usd"] is not None else None,
                       "mined": mined, "value": value, "current": e["symbol"] == self.current})
            mining = self.state in ("starting", "mining") and self.current
            hw, active = self._hardware(), tuning.user_active()
            algo = self.coins.get(self.current, {}).get("algo") if mining else None
            plan_threads = (self._turn if mining and self._turn else
                            tuning.settings(self.prefs["power"], hw, active))["threads"]
            return {
                "defender": {"blocked": self.defender_blocked, "folder_allowed": defender.miner_folder_allowed(),
                             "folder": str(store.MINERS)},
                "tuning": {
                    "tier": tuning.tier(hw), "cpu": hw.get("cpu"), "threads": plan_threads,
                    "base_threads": hw.get("rx_threads"), "all_threads": hw.get("threads"),
                    "ram_gb": hw.get("ram_gb"), "free_gb": hw.get("free_gb"), "memory": self._memory,
                    "active": active, "laptop": hw.get("laptop"),
                    "calibrated": (self._speed_key(algo) in self.learned) if algo else bool(self.learned),
                },
                "state": self.state,
                "message": self.message,
                "want": self.want,
                "current": {"symbol": self.current, "name": self.coins.get(self.current, {}).get("name", self.current),
                            "slice_left": max(0, SLICE_S - (now - self.slice_start)), "slice_len": SLICE_S} if mining else None,
                "hashrate": self.hashrate if self.state == "mining" else 0,
                "prefs": self.prefs,
                "entries": entries,
                "active_count": len(self.plan["active"]),
                "total_value": total,
                "unpriced": unpriced,
                "currency": currency,
                "power_cost_day": power_watts * 24 / 1000 * rate if mining else 0,
            }

    # ---- the loop -------------------------------------------------------------------------------

    def _loop(self) -> None:
        # Ticks run without the lock: they do slow network and process work, and the card polls snapshot().
        # Shared state is only ever swapped or appended to, never iterated while another thread changes it.
        while True:
            try:
                if not self._detached:
                    self._tick()
            except Exception:
                log.exception("engine tick failed")
                self._stop_miner()
                self._set("error", "Something went wrong. Retrying shortly…")
            self._wake.wait(TICK_S)
            self._wake.clear()

    def _tick(self) -> None:
        now = time.time()
        memory = tuning.memory_mode(self._hardware()) if self.lane == "cpu" else "fast"
        if memory != self._memory:  # free RAM crossed the line: RandomX speeds change, so replan
            log.info("RandomX memory mode %s -> %s", self._memory, memory)
            self._memory, self.plan_at = memory, 0
            if self._proc and self.coins.get(self.current, {}).get("family") == "rx":
                self._restart = True
        if now - self.plan_at > REPLAN_S:
            self._replan(now)
        if not self.want:
            self._stop_miner()
            if self.state != "blocked":
                self._set("stopped", "")
            return
        if self.prefs["pause_on_battery"] and on_battery():
            self._stop_miner()
            self._set("paused", "Paused while on battery. Plug in to continue.")
            return
        active = [s for s in self.plan["active"] if self.cooldown.get(s, 0) < now]
        if not active:
            self._stop_miner()
            if self.plan["active"]:
                self._set("paused", "The basket's pool isn't reachable right now. Retrying soon.")
            else:
                self._set("setup", "Add a wallet address for a coin in your basket to start.")
            return

        if self._proc and self._proc.poll() is not None:
            self._miner_died(now)
            return
        if self._proc:
            self._account(now)
            self._follow_activity()
            if self._miner.get("login_failed"):
                self._reject_current()
                return
            if (not self._miner["connected"] and self._miner["connect_errors"]
                    and now - self._miner["started"] > CONNECT_GRACE_S):
                # Pool unreachable: try this coin's next pool, and pause the coin once they've all failed
                symbol = self.current
                tried = self._pool_index.get(symbol, 0) + 1
                self._stop_miner()
                if tried < len(pools.options(self.coins[symbol], self.wallets.get(symbol, ""))):
                    self._pool_index[symbol] = tried
                    self._restart = True
                else:
                    self._pool_index[symbol] = 0
                    self.cooldown[symbol] = now + COOLDOWN_S
                return
        if (not self._proc or self.current not in active or self._restart
                or now - self.slice_start >= SLICE_S):
            keep_turn = self._restart and self.current in active and now - self.slice_start < SLICE_S
            symbol = self.current if keep_turn else self._next_coin(active)
            self._switch(symbol, now, new_turn=not keep_turn)

    def _replan(self, now: float) -> None:
        self.plan_at = now
        try:
            self.coins = {s: c for s, c in coins.get()["coins"].items() if c.get("lane", "cpu") == self.lane}
        except Exception as e:
            log.warning("coin list unavailable: %s", e)
            if not self.coins:
                self._set("error", str(e))
                return
        self.wallets = store.load("wallets.json") or {}
        estimates = self._estimate_speeds()
        speeds = {}
        for c in self.coins.values():
            algo = c["algo"]
            light = self._memory == "light" and algo.startswith("rx/")
            estimate = (estimates.get(algo) or estimates.get(c["family"]) or 0) * (tuning.LIGHT_FACTOR if light else 1)
            speeds[algo] = self.learned.get(self._speed_key(algo)) or estimate
        self.plan = basket.plan(self.coins, speeds, self.wallets, self.rejected, self.prefs["max_coins"],
                                featured=self.prefs.get("featured", True))
        self.turn_time = collections.Counter({s: t for s, t in self.turn_time.items() if s in self.plan["active"]})

    def _speed_key(self, algo: str) -> str:
        """Learned speeds are kept per RandomX memory mode: light mode is several times slower."""
        return f"{algo}@light" if self._memory == "light" and algo.startswith("rx/") else algo

    def _follow_activity(self) -> None:
        """Auto mode: yield the CPU the moment someone uses the PC, take it back when they stop."""
        if self.prefs["power"] != "auto" or not self._proc or self.lane != "cpu":
            return
        want = tuning.settings("auto", self._hardware(), tuning.user_active())["priority_class"]
        if want != self._priority and tuning.set_priority(self._proc, want):
            self._priority = want

    def _next_coin(self, active: list) -> str:
        """The coin furthest behind its share of mining time."""
        shares = {e["symbol"]: e["share"] for e in self.plan["entries"]}
        total = sum(self.turn_time[s] for s in active) + SLICE_S
        options = [s for s in active if s != self.current] or active
        return max(options, key=lambda s: (shares.get(s, 0) * total - self.turn_time[s], shares.get(s, 0)))

    # ---- the miner process ----------------------------------------------------------------------

    def _switch(self, symbol: str, now: float, new_turn: bool) -> None:
        self._stop_miner()
        self._restart = False
        coin = self.coins[symbol]
        self.current = symbol
        if new_turn:
            self.slice_start = now
        self._set("starting", f"Starting {coin['name']}…")
        driver = self._driver = miners.DRIVERS[coin.get("engine", "xmrig")]
        exe = driver.exe()
        if not exe and self.defender_blocked:  # a fresh download would just be removed again
            self._defender_block()
            return
        try:
            exe = exe or driver.install(lambda _pct, msg: self._set("starting", msg))
        except bench.BenchError as e:
            if "antivirus" in str(e).lower():
                self._defender_block()
            else:
                self.want = False
                self._set("blocked", str(e))
            return
        options = pools.options(coin, self.wallets[symbol])
        pool = options[self._pool_index.get(symbol, 0) % len(options)]
        port, token = _free_port(), secrets.token_urlsafe(16)
        self._turn = (tuning.settings(self.prefs["power"], self._hardware(), tuning.user_active())
                      if self.lane == "cpu" else dict(GPU_TURN))
        light = self._memory == "light" and coin["family"] == "rx"
        args = driver.args(exe, coin["algo"], pool, port, token, self._turn, light)
        # Output goes to a file, not a pipe: a pipe would break when this MINTRO exits for an update
        self._log_path, self._log_offset = store.DATA / f"miner{self._suffix}.log", 0
        try:
            with open(self._log_path, "wb") as out:
                self._proc = subprocess.Popen(args, cwd=exe.parent, stdout=out, stderr=subprocess.STDOUT,
                                              stdin=subprocess.DEVNULL, creationflags=hardware.NO_WINDOW)
        except OSError as e:
            log.warning("%s refused to start: %s", driver.title, e)
            self._defender_block()
            return
        host = f"{pool['name']} {pool['host']}"
        self._priority = (self._turn["priority_class"]
                          if tuning.set_priority(self._proc, self._turn["priority_class"]) else None)
        self._api, self._exe = ("127.0.0.1", port, token), str(exe)
        self._tail.clear()
        self._miner = {"started": now, "login_failed": False, "connected": False, "connect_errors": 0,
                       "got_speed": False, "shares": 0}
        self._last_tick = now
        threading.Thread(target=self._read_output, args=(self._proc, self._log_path, 0), daemon=True).start()
        log.info("mining %s with %s on %s:%s (%s, power %s, %s memory)", symbol, driver.title, host, pool["port"],
                 coin["algo"], self.prefs["power"], "light" if light else "fast")

    def _read_output(self, proc, path: Path, offset: int) -> None:
        """Follow the miner's log file while this is still the running miner."""
        facts, pending = self._miner, b""
        try:
            f = open(path, "rb")
        except OSError:
            return
        with f:
            f.seek(offset)
            while proc is self._proc:
                chunk = f.read(65536)
                if not chunk:
                    if proc.poll() is not None:
                        return
                    time.sleep(0.5)
                    continue
                *lines, pending = (pending + chunk).split(b"\n")
                self._log_offset = f.tell() - len(pending)
                for raw in lines:
                    line = raw.decode("utf-8", "replace").rstrip()
                    self._tail.append(line)
                    if LOGIN_ERROR.search(line):
                        facts["login_failed"] = True
                    elif NEW_JOB.search(line):
                        facts["connected"] = True
                    elif CONNECT_ERROR.search(line) and "error" in line.lower():
                        facts["connect_errors"] += 1

    def _account(self, now: float) -> None:
        dt, self._last_tick = now - self._last_tick, now
        _host, port, token = self._api
        h10, h60, good = self._driver.poll(port, token) if self._driver else (None, None, None)
        self.hashrate = h10 or (self.hashrate if self._miner["got_speed"] else 0)
        coin = self.coins.get(self.current)
        if not coin:
            return
        self.turn_time[self.current] += dt
        rec = self.ledger.setdefault(self.current, {"seconds": 0.0, "coins": 0.0, "shares": 0})
        rec["seconds"] += dt
        if good is not None and good > self._miner["shares"]:
            rec["shares"] += good - self._miner["shares"]
            self._miner["shares"] = good
        if self.hashrate:
            self._miner["got_speed"] = True
            mined = (self.hashrate / (coin["net_hps"] + self.hashrate) * dt / coin["block_time"]
                     * coin["reward"] * (1 - coin["fee"]))
            rec["coins"] += mined
            # Daily record for the tax report: amount and its dollar value at the price of the moment
            day = self.daily.setdefault(time.strftime("%Y-%m-%d"), {}).setdefault(
                self.current, {"coins": 0.0, "usd": 0.0, "priced": coin["price_usd"] is not None})
            day["coins"] += mined
            day["usd"] += mined * (coin["price_usd"] or 0)
            self._set("mining", f"Mining {coin['name']}")
        else:
            self._set("starting", f"Warming up {coin['name']}…")
        if h60 and now - self._miner["started"] > LEARN_AFTER_S:
            # Calibrate: store the speed scaled to the full thread count, since Auto changes threads with activity
            hw = self._hardware()
            if coin.get("engine") == "xmrig":
                base = hw.get("rx_threads") or 1
                used = max(1, min(self._turn.get("threads", base), base))
            elif coin.get("engine") == "cpuminer":
                base, used = hw.get("threads") or 1, max(1, self._turn.get("cpu_threads", 1))
            else:
                base = used = 1
            measured, key = h60 * base / used, self._speed_key(coin["algo"])
            old = self.learned.get(key)
            self.learned[key] = round(measured if not old else 0.8 * old + 0.2 * measured, 1)
        if now - self._last_save > 30:
            self._save()

    def _miner_died(self, now: float) -> None:
        lived = now - self._miner.get("started", now)
        tail = "\n".join(self._tail).lower()
        self._proc = None
        if self._miner.get("login_failed"):
            self._reject_current()
            return
        if lived < EARLY_EXIT_S and not self._miner.get("got_speed"):
            self.want = False
            if "failed to allocate" in tail:
                self._set("blocked", "Not enough free RAM for RandomX (it needs about 2.5 GB). Close some apps, then press Start.")
            else:
                self._defender_block()
            log.warning("miner exited after %.0fs:\n%s", lived, tail[-1500:])
            return
        log.warning("miner exited after %.0fs; moving on", lived)
        self.cooldown[self.current] = now + 60  # brief pause on this coin, then the loop picks the next one

    def _defender_block(self) -> None:
        self.want, self.defender_blocked = False, True
        if defender.miner_folder_allowed():
            self._set("blocked", f"Windows Security stopped {self._engine_title()} even though MINTRO's miner folder is allowed. "
                                 "Open Protection history, find the HashvaultMiner / CoinMiner item and choose "
                                 "Allow on device, then press Start.")
        else:
            self._set("blocked", f"Windows Security stopped {self._engine_title()}. It flags every crypto miner, and \"Allow\" doesn't "
                                 "last because each download is a new file. Let it skip MINTRO's miner folder; "
                                 "Windows will ask for admin permission.")

    def _engine_title(self) -> str:
        return self._driver.title if self._driver else "the miner"

    def _reject_current(self) -> None:
        symbol = self.current
        self._stop_miner()
        self.rejected.add(symbol)
        store.save(f"rejected{self._suffix}.json", sorted(self.rejected))
        self.plan_at = 0
        log.warning("pool rejected the %s address", symbol)

    def _stop_miner(self) -> None:
        proc, self._proc = self._proc, None
        self.hashrate = 0.0
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _set(self, state: str, message: str) -> None:
        self.state, self.message = state, message

    def _save(self) -> None:
        self._last_save = time.time()
        store.save(f"ledger{self._suffix}.json", self.ledger)
        store.save(f"speeds{self._suffix}.json", self.learned)
        store.save(f"daily{self._suffix}.json", self.daily)


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def on_battery() -> bool:
    if os.name != "nt":
        return False
    status = _PowerStatus()
    return bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))) and status.ACLineStatus == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
