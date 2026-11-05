"""MINTRO admin: coin listing requests in, signed listings out (publisher only; not part of the app).

    py -3.12 publisher\\admin.py          # opens http://127.0.0.1:8799 in your browser

1. Requests: what coin projects sent through the website's "List your coin" form (from the stats service).
2. Review: open a request, or Add coin, to fill in the listing. Run checks tests the algorithm, the pool
   (it connects and speaks stratum to it) and the links.
3. Preview: your own MINTRO switches to the new list straight away, before anyone else sees it.
4. Publish: bumps the serial, writes listings/listings.json, signs it with the publisher key, and commits and
   pushes it. Every installed MINTRO picks it up within a few hours, no app update needed.

The dashboard is a separate program for the publisher: it is not part of the MINTRO app people install, and
only someone who signs in with the admin password can use it. The first time it opens, it asks you to set
that password (stored only as a salted PBKDF2 hash). Sessions end after 8 idle hours or on Sign out; five
wrong passwords in a row lock sign-in for a minute. Forgot it? Delete "password" from admin.json; whoever can
do that already has your user account and your signing key, which is the real line of trust.

Settings (stats service URL and admin token, password hash) are kept in %USERPROFILE%\\MINTRO-publisher\\admin.json.
Docs: docs/LISTINGS.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(HERE)]
from mintro import coins, listings, market  # noqa: E402
import mintro_keys  # noqa: E402

PORT = 8799
FEED = ROOT / "listings" / "listings.json"
DRAFT = ROOT / "listings" / "listings.draft.json"
PUBLISHER = mintro_keys.KEY_FILE.parent
SETTINGS = PUBLISHER / "admin.json"
STAGING = PUBLISHER / "staging"
APP_DATA = [Path(os.environ.get("LOCALAPPDATA", "")) / "MINTRO" / "data", ROOT / "data"]  # installed, from source
SYMBOL = re.compile(r"^[A-Z0-9]{2,10}$")
SESSION_IDLE_S = 8 * 3600
PBKDF2_ROUNDS = 310_000
MIN_PASSWORD = 12


# ---- sign-in ---------------------------------------------------------------------------------------------

class Auth:
    """One admin password, sessions in memory (a restart signs everyone out), and a lockout after 5 misses."""

    def __init__(self):
        self.sessions: dict[str, float] = {}
        self.failures, self.locked_until = 0, 0.0
        self.lock = threading.Lock()

    @staticmethod
    def _hash(password: str, salt: bytes, rounds: int) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds).hex()

    def has_password(self) -> bool:
        return bool(settings().get("password"))

    def set_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters.")
        salt = secrets.token_bytes(16)
        s = settings()
        s["password"] = {"salt": salt.hex(), "rounds": PBKDF2_ROUNDS, "hash": self._hash(password, salt, PBKDF2_ROUNDS)}
        save_settings(s)
        with self.lock:
            self.sessions.clear()  # a new password signs everyone out

    def check_password(self, password: str) -> bool:
        stored = settings().get("password") or {}
        if not stored:
            return False
        got = self._hash(password, bytes.fromhex(stored["salt"]), int(stored["rounds"]))
        return hmac.compare_digest(got, stored["hash"])

    def sign_in(self, password: str) -> str:
        with self.lock:
            if time.time() < self.locked_until:
                raise ValueError(f"Too many tries. Wait {int(self.locked_until - time.time()) + 1} s.")
        if not self.check_password(password):
            with self.lock:
                self.failures += 1
                if self.failures >= 5:
                    self.failures, self.locked_until = 0, time.time() + 60
            time.sleep(0.5)
            raise ValueError("Wrong password.")
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.failures = 0
            self.sessions[token] = time.time() + SESSION_IDLE_S
        return token

    def valid(self, token: str | None) -> bool:
        with self.lock:
            expires = self.sessions.get(token or "")
            if not expires or expires < time.time():
                self.sessions.pop(token or "", None)
                return False
            self.sessions[token] = time.time() + SESSION_IDLE_S  # sliding idle timeout
            return True

    def sign_out(self, token: str | None) -> None:
        with self.lock:
            self.sessions.pop(token or "", None)


AUTH = Auth()


# ---- files ---------------------------------------------------------------------------------------------

def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def settings() -> dict:
    return load(SETTINGS, {})


def save_settings(s: dict) -> None:
    PUBLISHER.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")


def published() -> dict:
    return load(FEED, {"serial": 0, "coins": []})


def write_feed(path: Path, serial: int, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    feed = {"serial": serial, "issued": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "coins": sorted(entries, key=lambda c: c["symbol"])}
    # Fixed LF line endings: the signature covers these exact bytes, on every OS and through git
    path.write_text(json.dumps(feed, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    mintro_keys.sign_listings(path)


# ---- the stats service (listing requests) --------------------------------------------------------------

def service(path: str, body: dict | None = None) -> dict:
    s = settings()
    if not s.get("stats_url") or not s.get("admin_token"):
        raise ValueError("Add the stats service URL and admin token in Settings first.")
    req = urllib.request.Request(s["stats_url"].rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Authorization": f"Bearer {s['admin_token']}", "Content-Type": "application/json",
                                          "User-Agent": "mintro-admin"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


# ---- checks ----------------------------------------------------------------------------------------------

def check(entry: dict, others: list) -> list[dict]:
    out = []

    def note(level, text):
        out.append({"level": level, "text": text})

    sym = str(entry.get("symbol", "")).upper()
    note("ok" if SYMBOL.match(sym) else "fail", f"Ticker {sym or '(empty)'}" + ("" if SYMBOL.match(sym) else ": use 2-10 letters or digits"))
    if sum(1 for o in others if str(o.get("symbol", "")).upper() == sym) > 1:
        note("fail", f"{sym} is listed twice")
    if not entry.get("name"):
        note("fail", "Name is missing")
    tier, status = entry.get("tier", "standard"), entry.get("status", "listed")
    if tier not in ("standard", "featured", "promo"):
        note("fail", "Tier must be standard, featured or promo")
    if status not in ("listed", "paused", "delisted"):
        note("fail", "Status must be listed, paused or delisted")
    if tier == "featured":
        share = float(entry.get("min_share") or 0)
        note("ok" if 0 < share <= listings.MAX_FEATURED_SHARE else "fail",
             f"Featured share {share:.0%}" + ("" if 0 < share <= listings.MAX_FEATURED_SHARE else f": between 1% and {listings.MAX_FEATURED_SHARE:.0%}"))
    until = entry.get("until") or ""
    if until and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", until):
        note("fail", "Until must be a date (YYYY-MM-DD)")
    elif until and until < time.strftime("%Y-%m-%d"):
        note("warn", f"Expired on {until}: it won't show")
    for k, v in (entry.get("links") or {}).items():
        if v and not str(v).startswith("https://"):
            note("fail", f"The {k} link must start with https://")
    if len(entry.get("pitch") or "") > 200:
        note("fail", "Pitch is longer than 200 characters")
    if tier == "promo":
        note("ok", "Promo: shown in the Sponsored box, not mined")
        return out

    if entry.get("source", "rplant") == "rplant":
        try:
            pool = coins._rplant(force=True)["coins"]
        except Exception as e:
            note("warn", f"Couldn't reach rplant to check: {e}")
            return out
        if sym in pool:
            c = pool[sym]
            note("ok", f"On rplant: {c['name']}, {c['algo']}, {c['miners']} miners, {c['block_time']:.0f} s blocks")
        else:
            note("fail", f"{sym} isn't on the rplant pool with an algorithm MINTRO mines (or rplant lists it on two algorithms)")
        return out

    algo = entry.get("algo")
    note("ok" if algo in coins.ENGINES else "fail",
         f"Algorithm {algo}" + (f": mined with {coins.ENGINES[algo][0]}" if algo in coins.ENGINES
                                else f": MINTRO mines {', '.join(coins.ENGINES)}"))
    pools = entry.get("pools") or []
    if not pools:
        note("fail", "Add at least one pool")
    for p in pools:
        note(*_probe_pool(p))
    net = dict(entry.get("network") or {})
    if entry.get("network_api"):
        try:
            live = market.fetch_json(entry["network_api"], timeout=10)
            net.update({k: live[k] for k in ("hashrate", "block_time", "reward", "min_payout", "fee", "price_usd", "miners") if k in live})
            note("ok", f"Network API answered: {', '.join(f'{k} {v}' for k, v in live.items() if k in net)}")
        except Exception as e:
            note("warn", f"Network API didn't answer ({e}); the numbers below are used")
    for k in ("hashrate", "block_time", "reward"):
        try:
            ok = float(net.get(k) or 0) > 0
        except (TypeError, ValueError):
            ok = False
        note("ok" if ok else "fail", f"Network {k.replace('_', ' ')}: {net.get(k) or 'missing'}")
    try:
        if float(net.get("hashrate") or 0) > 0:
            per_day = 5000 / (float(net["hashrate"]) + 5000) * 86400 / float(net["block_time"]) * float(net["reward"])
            note("ok", f"A typical laptop (5 kH/s) would mine about {per_day:.4g} {sym} a day on this coin")
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return out


def _probe_pool(p: dict) -> tuple[str, str]:
    host, port, tls = str(p.get("host") or ""), int(p.get("port") or 0), bool(p.get("tls"))
    if not host or not port:
        return "fail", "Pool needs a host and a port"
    try:
        sock = socket.create_connection((host, port), timeout=6)
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # miners don't verify pool certificates either
            sock = ctx.wrap_socket(sock, server_hostname=host)
        sock.settimeout(6)
        sock.sendall(b'{"id":1,"method":"mining.subscribe","params":["mintro-admin"]}\n')
        reply = sock.recv(512)
        sock.close()
        if reply.strip().startswith(b"{"):
            return "ok", f"Pool {host}:{port}{' (TLS)' if tls else ''} answered as a stratum server"
        return "warn", f"Pool {host}:{port} is reachable but didn't answer stratum"
    except (OSError, ssl.SSLError) as e:
        return "fail", f"Pool {host}:{port}{' (TLS)' if tls else ''} unreachable: {e.__class__.__name__}"


# ---- preview and publish ------------------------------------------------------------------------------

def preview(entries: list) -> str:
    serial = published().get("serial", 0) + 1
    write_feed(STAGING / "listings.json", serial, entries)
    url = f"http://127.0.0.1:{PORT}/staging/listings.json"
    _set_app_feed(url)
    return f"Your MINTRO now uses this list (serial {serial}). Others see nothing until you publish."


def stop_preview() -> None:
    _set_app_feed(None)


def _set_app_feed(url: str | None) -> None:
    for data in APP_DATA:
        prefs_path = data / "app-prefs.json"
        if not data.exists():
            continue
        prefs = load(prefs_path, {})
        if url:
            prefs["listings_feed"] = url
        else:
            prefs.pop("listings_feed", None)
        prefs_path.write_text(json.dumps(prefs, indent=1), encoding="utf-8")
        cache = load(data / "listings.json", {})
        if url is None:
            cache.pop("feed", None)  # drop the preview copy; the published feed is fetched again
        cache["checked"] = 0
        (data / "listings.json").write_text(json.dumps(cache), encoding="utf-8")
    try:  # a running MINTRO reloads at once
        req = urllib.request.Request("http://127.0.0.1:8777/api/listings/refresh", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()
    except Exception:
        pass


def publish(entries: list, push: bool, message: str) -> list[str]:
    problems = [f"{e.get('symbol')}: {c['text']}" for e in entries for c in check(e, entries)
                if c["level"] == "fail" and e.get("status", "listed") == "listed"]
    if problems:
        raise ValueError("Fix these first: " + "; ".join(problems[:6]))
    old = published()
    serial = old.get("serial", 0) + 1
    write_feed(FEED, serial, entries)
    log = [f"Wrote and signed listings/listings.json (serial {serial}, {len(entries)} entries)"]
    DRAFT.unlink(missing_ok=True)
    stop_preview()
    if (ROOT / ".git").exists():
        summary = message.strip() or summarize(old.get("coins", []), entries)
        for cmd in (["git", "add", "listings/listings.json", "listings/listings.json.sig"],
                    ["git", "commit", "-m", f"Listings {serial}: {summary}"]):
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            log.append(f"$ {' '.join(cmd[:3])}… {'ok' if r.returncode == 0 else r.stderr.strip() or r.stdout.strip()}")
        if push:
            r = subprocess.run(["git", "push"], cwd=ROOT, capture_output=True, text=True)
            log.append("Pushed to GitHub: every running MINTRO picks it up within about 15 minutes" if r.returncode == 0
                       else f"Push failed: {r.stderr.strip()}")
        else:
            log.append("Committed but not pushed: push when you're ready")
    else:
        log.append("Not a git repository: upload listings/listings.json and its .sig to the repository yourself")
    return log


def summarize(before: list, after: list) -> str:
    b, a = {c["symbol"]: c for c in before}, {c["symbol"]: c for c in after}
    parts = [f"add {s}" for s in a if s not in b] + [f"remove {s}" for s in b if s not in a]
    parts += [f"update {s}" for s in a if s in b and a[s] != b[s]]
    return ", ".join(parts) or "no changes"


# ---- web UI ----------------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body, ctype="application/json", cookie: str | None = None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        if cookie is not None:
            self.send_header("Set-Cookie", f"mintro_admin={cookie}; HttpOnly; SameSite=Strict; Path=/"
                                           + ("" if cookie else "; Max-Age=0"))
        self.end_headers()
        self.wfile.write(data)

    def _token(self) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "mintro_admin":
                return value
        return None

    def _signed_in(self) -> bool:
        if AUTH.valid(self._token()):
            return True
        self._send(401, {"error": "Sign in first.", "signin": True})
        return False

    def _guard(self) -> bool:
        if self.headers.get("Host") not in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            self._send(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        try:
            if self.path == "/":
                self._send(200, (HERE / "admin.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path in ("/staging/listings.json", "/staging/listings.json.sig"):
                # The preview feed for this PC's own MINTRO: signed, and only served on 127.0.0.1
                self._send(200, (STAGING / Path(self.path).name).read_bytes())
            elif self.path == "/api/session":
                self._send(200, {"signed_in": AUTH.valid(self._token()), "has_password": AUTH.has_password()})
            elif not self._signed_in():
                return
            elif self.path == "/api/state":
                s = settings()
                self._send(200, {"settings": {"stats_url": s.get("stats_url", ""), "has_token": bool(s.get("admin_token"))},
                                 "published": published(), "draft": load(DRAFT, None), "algos": list(coins.ENGINES),
                                 "max_featured": listings.MAX_FEATURED_SHARE, "git": (ROOT / ".git").exists(),
                                 "key": mintro_keys.KEY_FILE.exists()})
            elif self.path == "/api/requests":
                self._send(200, service("/v1/admin/requests"))
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})

    def do_POST(self):
        if not self._guard():
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._send(415, {"error": "JSON only"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if self.path == "/api/setup":  # first run only: choose the admin password
                if AUTH.has_password():
                    raise ValueError("An admin password is already set. Sign in instead.")
                AUTH.set_password(str(body.get("password", "")))
                return self._send(200, {"ok": True}, cookie=AUTH.sign_in(str(body.get("password", ""))))
            if self.path == "/api/login":
                return self._send(200, {"ok": True}, cookie=AUTH.sign_in(str(body.get("password", ""))))
            if self.path == "/api/logout":
                AUTH.sign_out(self._token())
                return self._send(200, {"ok": True}, cookie="")
            if not self._signed_in():
                return
            m = re.fullmatch(r"/api/requests/(\d+)", self.path)
            if self.path == "/api/password":
                if not AUTH.check_password(str(body.get("current", ""))):
                    raise ValueError("The current password is wrong.")
                AUTH.set_password(str(body.get("new", "")))
                self._send(200, {"ok": True}, cookie=AUTH.sign_in(str(body.get("new", ""))))
            elif m:
                self._send(200, service(f"/v1/admin/requests/{m[1]}", {"status": body.get("status"), "note": body.get("note", "")}))
            elif self.path == "/api/settings":
                s = settings()
                s["stats_url"] = str(body.get("stats_url", s.get("stats_url", ""))).strip()
                if body.get("admin_token"):
                    s["admin_token"] = str(body["admin_token"]).strip()
                save_settings(s)
                self._send(200, {"ok": True})
            elif self.path == "/api/draft":
                DRAFT.parent.mkdir(parents=True, exist_ok=True)
                DRAFT.write_text(json.dumps({"coins": body.get("coins", [])}, indent=1), encoding="utf-8")
                self._send(200, {"ok": True})
            elif self.path == "/api/check":
                self._send(200, {"checks": check(body.get("entry", {}), body.get("all", []))})
            elif self.path == "/api/preview":
                self._send(200, {"message": preview(body.get("coins", []))})
            elif self.path == "/api/preview/stop":
                stop_preview()
                self._send(200, {"message": "Your MINTRO is back on the published list."})
            elif self.path == "/api/publish":
                self._send(200, {"log": publish(body.get("coins", []), bool(body.get("push")), str(body.get("message", "")))})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})


def main() -> None:
    if not mintro_keys.KEY_FILE.exists():
        sys.exit(f"No publisher signing key at {mintro_keys.KEY_FILE}. Run: py publisher\\mintro_keys.py init")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"MINTRO admin running at {url} (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
