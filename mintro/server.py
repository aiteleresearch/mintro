"""Local web server: serves the card and report pages and a small JSON API on 127.0.0.1 only."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (bench, calc, coins, config, defender, engine, extras, gpu, hardware, listings, market, miners,
               partners, selftest, store, telemetry, updater, wallets)

log = logging.getLogger("mintro")
WEB = Path(__file__).resolve().parent / "web"
PAGES = {"/": "index.html", "/card": "card.html"}
HW_MAX_AGE = 120     # re-check free RAM / charger this often (seconds)
IDLE_QUIT = 180      # browser mode: quit this long after the page was closed (seconds)
NEVER_OPENED_QUIT = 600


class App:
    def __init__(self):
        self.bench = bench.Job()
        self.last_seen = 0.0
        self._hw: dict | None = None
        self._hw_at = 0.0
        self._hw_lock = threading.Lock()
        self._settings_lock = threading.Lock()
        self.engine = engine.Engine(self.algo_speeds, self.hardware)                       # CPU lane
        self.gpu_engine = engine.Engine(self.gpu_speeds, self.hardware, lane="gpu")        # GPU lane
        self.wallet_jobs = wallets.Jobs(self.all_coins, self.set_address)
        self.alerts = extras.Alerts()
        self.updater = updater.Updater()
        self.heartbeat = telemetry.Heartbeat()
        self.quit = None  # set by the desktop card: closes the window (and so MINTRO)
        self._sponsored, self._sponsored_at = [], 0.0
        self._listings_serial = None
        threading.Thread(target=self._background, daemon=True, name="mintro-background").start()

    # ---- lanes -----------------------------------------------------------------------------------------

    def all_coins(self) -> dict:
        return {**self.engine.coins, **self.gpu_engine.coins}

    def set_address(self, symbol: str, address: str) -> None:
        (self.gpu_engine if symbol in self.gpu_engine.coins else self.engine).set_address(symbol, address)

    def gpu_card(self) -> dict | None:
        return gpu.discrete(self.hardware())

    def gpu_enabled(self) -> bool:
        """GPU mining runs on PCs with a discrete GPU: on by default on desktops, opt-in on laptops (heat, fans)."""
        return bool(self.gpu_card()) and app_prefs().get("gpu_enabled", not self.hardware().get("laptop"))

    def gpu_speeds(self) -> dict:
        card = self.gpu_card()
        return {"progpow": card["hps"]} if card else {}

    def start(self) -> None:
        self.engine.start()
        if self.gpu_enabled():
            self.gpu_engine.start()

    def stop(self) -> None:
        self.engine.stop()
        self.gpu_engine.stop()

    def start_updates(self, quit_app) -> None:
        """Desktop card only: look for updates in the background; quit_app() closes MINTRO for the swap."""
        self.quit = quit_app
        threading.Thread(target=self.updater.run, args=(self.handoff_and_quit,), daemon=True,
                         name="mintro-updates").start()

    def handoff_and_quit(self) -> bool:
        """Leave the miners mining for the next version, then close MINTRO (an update or reinstall follows)."""
        if not self.quit:
            return False
        handed = [lane.detach() for lane in (self.engine, self.gpu_engine)]
        log.info("closing for an update or reinstall; miners handed over: %s", handed)
        self.bench.stop()
        wallets.stop_all()
        threading.Timer(0.5, self.quit).start()
        return True

    def _background(self) -> None:
        """Every 30 s: new coin listings, alerts, the My PCs status file, and the GPU lane in step with the CPU lane."""
        while True:
            time.sleep(30)
            try:
                self.watch_listings()
                if self.engine.want and self.gpu_enabled() and not self.gpu_engine.want:
                    self.gpu_engine.start()
                elif self.gpu_engine.want and (not self.engine.want or not self.gpu_enabled()):
                    self.gpu_engine.stop()
                lanes = [e.lane for e in (self.engine, self.gpu_engine) if e.state == "mining"]
                self.heartbeat.tick(bool(lanes), lanes)
                snap = self.state()
                self.alerts.check(snap)
                extras.publish(snap)
            except Exception:
                log.exception("background check failed")

    def watch_listings(self) -> bool:
        """When the admin publishes a new listings feed, replan both lanes now instead of at the next replan.

        Returns True if a new feed arrived. The feed itself is checked every listings.TTL seconds.
        """
        serial = listings.serial()
        changed = self._listings_serial is not None and serial != self._listings_serial
        self._listings_serial = serial
        if changed:
            log.info("new coin listings (serial %s): replanning", serial)
            self._sponsored_at = 0.0
            for lane in (self.engine, self.gpu_engine):
                lane.plan_at = 0
                lane._wake.set()
        return changed

    def hardware(self) -> dict:
        with self._hw_lock:
            if self._hw is None:
                # Last run's result makes startup instant (detection can take 30 s+ on a busy, low-RAM laptop)
                cached = store.load("hardware.json")
                if cached and cached.get("cpu"):
                    self._hw, self._hw_at = cached, 0.0
                else:
                    self._hw, self._hw_at = hardware.detect(), time.time()
                    store.save("hardware.json", self._hw)
            if time.time() - self._hw_at > HW_MAX_AGE:
                self._hw_at = time.time()
                threading.Thread(target=self._refresh_hardware, daemon=True).start()
            return self._hw

    def _refresh_hardware(self) -> None:
        try:
            hw = hardware.detect()
        except Exception:
            log.exception("hardware refresh failed")
            return
        with self._hw_lock:
            if hw.get("source") == "generic" and (self._hw or {}).get("source") == "cim":
                return  # a timed-out Windows query: keep the real data we already have
            self._hw = hw
        store.save("hardware.json", hw)

    def _speeds(self) -> dict:
        hw = self.hardware()
        return calc.speeds(hw, bench.load_result(hw["cpu"]))

    def algo_speeds(self) -> dict:
        """Estimated H/s per algorithm or speed family, for planning before MINTRO has measured anything."""
        sp = self._speeds()
        out = {f: s["hps"] for f, s in sp.items()}
        out.update({"rx/0": sp["rx"]["hps"], "rx/arq": sp["rx"]["hps"], "rx/wow": sp["rx"]["hps"]})
        return out

    def _settings(self, refresh: bool = False) -> tuple[dict, dict]:
        """Saved currency + electricity price (first run: region defaults) and market data in that currency."""
        hw = self.hardware()
        with self._settings_lock:
            s = store.load("settings.json") or {}
            s.setdefault("currency", hw.get("currency") or "USD")
            mk = market.get(s["currency"], force=refresh)
            if s["currency"].lower() not in mk["btc"]:  # no prices in that currency: fall back to dollars
                s = {"currency": "USD"}
                mk = market.get("USD")
            if "rate" not in s:
                s["rate"] = calc.default_rate(s["currency"], mk["btc"])
                store.save("settings.json", s)
        return s, mk

    def report(self, refresh: bool = False) -> dict:
        hw = self.hardware()
        s, mk = self._settings(refresh)
        return calc.report(hw, mk, s, bench.load_result(hw["cpu"]), self.bench.status())

    def state(self) -> dict:
        try:
            s, mk = self._settings()
            cur = s["currency"]
            fx = mk["btc"][cur.lower()] / mk["btc"]["usd"]
        except Exception:  # offline on first run: show dollars
            s, cur, fx = {"rate": calc.DEFAULT_RATES["USD"]}, "USD", 1.0
        rate = float(s["rate"])
        snap = self.engine.snapshot(fx, cur, self._speeds()["rx"]["watts"], rate)
        snap["cpu"] = self.hardware().get("cpu")
        snap["rate"] = rate
        card = self.gpu_card()
        if card:
            g = self.gpu_engine.snapshot(fx, cur, card["watts"], rate)
            for e in g["entries"]:
                e["lane"] = "gpu"
            snap["entries"] += g["entries"]
            snap["active_count"] += g["active_count"]
            snap["total_value"] += g["total_value"]
            snap["power_cost_day"] += g["power_cost_day"]
            snap["gpu"] = {"name": card["name"], "enabled": self.gpu_enabled(), "state": g["state"],
                           "message": g["message"], "coin": (g["current"] or {}).get("name"), "hashrate": g["hashrate"]}
        else:
            snap["gpu"] = {"name": None}
        coins_now, jobs = self.all_coins(), self.wallet_jobs.status()
        for e in snap["entries"]:
            sym, coin = e["symbol"], coins_now.get(e["symbol"], {})
            e["wallet"] = {"supported": wallets.supported(sym), "created": wallets.created(sym), "job": jobs.get(sym)}
            e["markets"] = partners.market_links(coin)
            e["hardware_wallets"] = partners.hardware_wallets(sym)
        if time.time() - self._sponsored_at > 60:
            self._sponsored, self._sponsored_at = partners.sponsored(coins_now), time.time()
        snap["sponsored"] = self._sponsored
        snap["extras"] = {"fleet_folder": str(extras.fleet_folder() or ""), "fleet": extras.fleet(),
                          "fleet_suggestion": extras.default_fleet_folder(), "alerts": list(self.alerts.recent)}
        snap["engine_fees"] = [d.fee_note for d in miners.DRIVERS.values() if d.fee_note]
        snap["expectations_seen"] = bool(app_prefs().get("expectations_seen"))
        snap["app"] = {**self.updater.status(), "share_stats": telemetry.enabled(), "stats_on": bool(config.STATS_URL)}
        return snap

    def update_settings(self, body: dict) -> dict:
        with self._settings_lock:
            self._apply_settings(body)
        return self.report()

    def _apply_settings(self, body: dict) -> None:
        s = store.load("settings.json") or {}
        if "currency" in body:
            cur = str(body["currency"]).upper()
            if not re.fullmatch(r"[A-Z]{3}", cur):
                raise ValueError("Unknown currency.")
            mk = market.get(cur)
            if cur.lower() not in mk["btc"]:
                raise ValueError(f"No live prices are available in {cur}.")
            if cur != s.get("currency"):
                s["currency"], s["rate"] = cur, calc.default_rate(cur, mk["btc"])
        if "rate" in body:
            rate = float(body["rate"])
            if not 0 <= rate < 1e6:
                raise ValueError("Electricity price must be zero or more.")
            s["rate"] = rate
        store.save("settings.json", s)

    def warm_up(self) -> None:
        """Detect hardware and fetch prices before the page asks, so the first view is instant."""
        try:
            self.report()
        except Exception:
            log.exception("warm-up failed")


def app_prefs() -> dict:
    """App-level choices (GPU lane, My PCs folder, notices seen), kept apart from the engines' prefs.json."""
    return store.load("app-prefs.json") or {}


def set_app_pref(key: str, value) -> None:
    store.save("app-prefs.json", {**app_prefs(), key: value})


class Handler(BaseHTTPRequestHandler):
    app: App
    allowed_hosts: set = set()

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self) -> bool:
        # Refuse other hostnames (DNS rebinding) so only this machine's browser can use the API
        if self.headers.get("Host") not in self.allowed_hosts:
            self._send(403, {"error": "forbidden"})
            return False
        self.app.last_seen = time.time()
        return True

    def do_GET(self):
        if not self._guard():
            return
        url = urlparse(self.path)
        try:
            if url.path in PAGES:
                self._send(200, (WEB / PAGES[url.path]).read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/ping":
                self._send(200, {"app": "mintro"})
            elif url.path == "/api/state":
                self._send(200, self.app.state())
            elif url.path == "/api/report":
                self._send(200, self.app.report(refresh="refresh" in parse_qs(url.query)))
            elif url.path == "/api/bench":
                self._send(200, self.app.bench.status())
            else:
                self._send(404, {"error": "not found"})
        except ConnectionError:
            pass  # the card closed mid-request
        except Exception as e:
            log.exception("GET %s failed", url.path)
            self._send(503, {"error": str(e)})

    def do_POST(self):
        if not self._guard():
            return
        # JSON-only: browsers won't let other websites send this cross-origin without a preflight we never answer
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._send(415, {"error": "JSON only"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            eng = self.app.engine
            if self.path == "/api/log":
                log.warning("card %s: %s", str(body.get("kind"))[:20], str(body.get("msg"))[:600])
                return self._send(200, {"ok": True})
            log.info("card -> %s", self.path)
            app = self.app
            if self.path == "/api/start":
                app.start()
                self._send(200, app.state())
            elif self.path == "/api/stop":
                app.stop()
                self._send(200, app.state())
            elif self.path == "/api/address":
                app.set_address(str(body.get("symbol", "")), str(body.get("address", "")))
                self._send(200, app.state())
            elif self.path == "/api/prefs":
                eng.set_prefs(body)
                self._send(200, self.app.state())
            elif self.path == "/api/wallet/create":
                self.app.wallet_jobs.create([str(s) for s in body.get("symbols") or []])
                self._send(200, self.app.state())
            elif self.path == "/api/wallet/seed":
                symbol = str(body.get("symbol", ""))
                if not wallets.created(symbol):
                    raise ValueError("MINTRO didn't create a wallet for this coin.")
                self._send(200, wallets.backup(symbol))
            elif self.path == "/api/wallet/open":
                wallets.open_folder(str(body.get("symbol", "")))
                self._send(200, {"ok": True})
            elif self.path == "/api/defender/allow":
                # Windows shows its admin prompt; nothing changes unless the person approves it there
                result = defender.allow_miner_folder()
                log.info("Windows Security exclusion for the miner folder: %s", result)
                if result == "ok":
                    eng.clear_block()
                    app.gpu_engine.clear_block()
                    app.start()
                self._send(200, {"result": result, **app.state()})
            elif self.path == "/api/defender/open":
                defender.open_protection_history()
                self._send(200, {"ok": True})
            elif self.path == "/api/extras/tax":
                path = extras.tax_report({s: c["name"] for s, c in app.all_coins().items()})
                os.startfile(path.parent)
                self._send(200, {"path": str(path)})
            elif self.path == "/api/extras/fleet":
                folder = str(body.get("folder", "")).strip()
                if folder and not Path(folder).is_absolute():
                    raise ValueError("Use a full folder path, e.g. C:\\Users\\you\\OneDrive\\MINTRO PCs")
                set_app_pref("fleet_folder", folder)
                self._send(200, app.state())
            elif self.path == "/api/gpu":
                set_app_pref("gpu_enabled", bool(body.get("enabled")))
                if app.gpu_enabled() and app.engine.want:
                    app.gpu_engine.start()
                elif not app.gpu_enabled():
                    app.gpu_engine.stop()
                self._send(200, app.state())
            elif self.path == "/api/selftest":
                self._send(200, {"checks": selftest.run(app)})
            elif self.path == "/api/ack":
                set_app_pref("expectations_seen", True)
                self._send(200, {"ok": True})
            elif self.path == "/api/share-stats":
                set_app_pref("share_stats", bool(body.get("enabled")))
                self._send(200, app.state())
            elif self.path == "/api/update/check":
                threading.Thread(target=app.updater.check_safely, daemon=True).start()
                time.sleep(0.2)
                self._send(200, app.state())
            elif self.path == "/api/update/install":
                if not app.updater.install_now(app.handoff_and_quit):
                    raise ValueError(app.updater.message if app.updater.state == "error" else "No update is ready to install.")
                self._send(200, app.state())
            elif self.path == "/api/update/seen":
                app.updater.just_updated = None
                self._send(200, {"ok": True})
            elif self.path == "/api/listings/refresh":
                # The admin tool switched this PC to a preview list (or back): reload it and replan now
                listings.feed(force=True)
                coins.get(force=True)
                for lane in (app.engine, app.gpu_engine):
                    lane.plan_at = 0
                    lane._wake.set()
                self._send(200, {"ok": True})
            elif self.path == "/api/handoff":
                # The installer is about to replace MINTRO: keep mining, close, and let the new version adopt it
                self._send(200, {"ok": app.handoff_and_quit()})
            elif self.path == "/api/settings":
                self._send(200, self.app.update_settings(body))
            elif self.path == "/api/bench":
                self._send(200, self.app.bench.start(self.app.hardware()))
            else:
                self._send(404, {"error": "not found"})
        except (ValueError, wallets.WalletError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            log.exception("POST %s failed", self.path)
            self._send(503, {"error": str(e)})


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets two programs share a port; we want a clean "port busy" error instead
    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def start(port: int) -> tuple[Server, App, str]:
    """Start the server on a background thread; returns (server, app, base url)."""
    app = App()
    Handler.app = app
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError:
        httpd = Server(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    Handler.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    threading.Thread(target=httpd.serve_forever, daemon=True, name="mintro-http").start()
    threading.Thread(target=app.warm_up, daemon=True).start()
    # Started and serving: tell a waiting update helper this version works
    threading.Timer(5, updater.mark_healthy).start()
    return httpd, app, f"http://127.0.0.1:{port}/"


def run(port: int, open_browser: bool = True, page: str = "") -> None:
    """Browser mode: serve until the page has been closed for a while (or Ctrl+C)."""
    if already_running(port):
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/{page}")
        print("MINTRO is already running.")
        return
    httpd, app, url = start(port)
    if open_browser:
        webbrowser.open(url + page)
    print(f"MINTRO is running at {url}\nClose this window to quit.")
    try:
        _wait_until_closed(app, auto_quit=open_browser)
    except KeyboardInterrupt:
        pass
    finally:
        app.engine.shutdown()
        app.gpu_engine.shutdown()
        app.bench.stop()
        wallets.stop_all()
        httpd.shutdown()


def _wait_until_closed(app: App, auto_quit: bool) -> None:
    """The page pings every 20 s; once it has been gone for a while (and nothing is mining), stop."""
    started = time.time()
    while True:
        time.sleep(15)
        if not auto_quit:
            continue
        idle = time.time() - (app.last_seen or started)
        if idle > (IDLE_QUIT if app.last_seen else NEVER_OPENED_QUIT) and not app.bench.running() and not app.engine.want:
            return


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read()).get("app") == "mintro"
    except Exception:
        return False
