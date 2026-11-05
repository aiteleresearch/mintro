"""One-click wallets: create a wallet for a basket coin with that coin's own official wallet tool.

For Monero-family coins MINTRO downloads the coin's official command-line release (checked against the
SHA-256 its developers publish, where they publish one), runs its wallet-rpc offline on 127.0.0.1 behind a
random login, asks it for a new wallet, and keeps the wallet files plus a plain-text backup in
wallets/<SYMBOL>/. The address goes straight into the basket. To spend, open that wallet in the coin's
official wallet app.
"""
from __future__ import annotations

import collections
import hashlib
import http.client
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import basket, hardware, market, store

log = logging.getLogger("mintro.wallets")

WALLETS = store.ROOT / "wallets"
TOOLS = store.ROOT / "tools"
RESTORE_MARGIN = 720   # start scanning about a day of blocks before "now", in case the pool's height lags
RPC_START_S = 90

# Where each coin's official Windows command-line tools are published
SOURCES = {
    "XMR": {"repo": "monero-project/monero", "url": "https://downloads.getmonero.org/cli/monero-win-x64-{tag}.zip",
            "sums_url": "https://www.getmonero.org/downloads/hashes.txt"},
    "ZEPH": {"repo": "ZephyrProtocol/Zephyr", "asset": r"^zephyr-cli-windows-.*\.zip$"},
    "SAL": {"repo": "salvium/salvium", "asset": r"^salvium-.*-win64\.zip$", "sums_in_notes": True},
    "MYT": {"repo": "MYT-Core/MYT", "asset": r"^myt-.*-win64\.zip$", "sums_asset": r"^SHA256SUMS-.*-win64\.txt$"},
}
# Not here: PDC ships only an old interactive "simplewallet", BMR publishes no wallet download, and
# RTM/BBC wallets need their full blockchain downloaded before they can make an address.


class WalletError(Exception):
    """A failure with a message meant for the user."""


def supported(symbol: str) -> bool:
    return os.name == "nt" and symbol in SOURCES


def created(symbol: str) -> bool:
    return (WALLETS / symbol / "backup.json").exists()


def backup(symbol: str) -> dict:
    """Seed words, address, restore height and file paths of a wallet MINTRO created."""
    data = json.loads((WALLETS / symbol / "backup.json").read_text(encoding="utf-8"))
    return {k: data[k] for k in ("symbol", "name", "address", "seed", "restore_height", "wallet_file", "backup_file")}


def stop_all() -> None:
    """Stop any wallet tool MINTRO started (called when MINTRO quits)."""
    for rpc in list(_WalletRpc.running):
        rpc._stop()


def open_folder(symbol: str) -> None:
    folder = WALLETS / symbol
    if not folder.is_dir():
        raise WalletError("That wallet's folder doesn't exist.")
    os.startfile(folder)


class Jobs:
    """Creates wallets one at a time on a background thread; the card polls status()."""

    def __init__(self, coins_provider, on_created):
        self._coins = coins_provider   # () -> {symbol: coin}
        self._on_created = on_created  # (symbol, address) -> None
        self._lock = threading.Lock()
        self._queue: collections.deque = collections.deque()
        self._status: dict = {}
        self._thread: threading.Thread | None = None

    def status(self) -> dict:
        with self._lock:
            return {s: dict(v) for s, v in self._status.items()}

    def create(self, symbols: list) -> None:
        with self._lock:
            for s in symbols:
                if not supported(s):
                    raise WalletError(f"MINTRO can't create {s} wallets yet. Paste an address from its official wallet.")
                busy = self._status.get(s, {}).get("state") not in (None, "done", "error")
                if not busy and not created(s) and s not in self._queue:
                    self._queue.append(s)
                    self._status[s] = {"state": "queued", "progress": 0, "message": "Waiting…"}
            if self._queue and not (self._thread and self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, daemon=True, name="mintro-wallets")
                self._thread.start()

    def _set(self, symbol: str, state: str, progress: float, message: str) -> None:
        with self._lock:
            self._status[symbol] = {"state": state, "progress": round(progress), "message": message}

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                symbol = self._queue.popleft()
            report = lambda state, progress, message: self._set(symbol, state, progress, message)
            try:
                coin = self._coins().get(symbol)
                if not coin:
                    raise WalletError("This coin isn't in the coin list right now.")
                rpc = install(symbol, report)
                result = create_wallet(symbol, coin, rpc, report)
                self._on_created(symbol, result["address"])
                self._set(symbol, "done", 100, "Wallet created")
            except WalletError as e:
                self._set(symbol, "error", 0, str(e))
            except Exception as e:
                log.exception("creating the %s wallet failed", symbol)
                self._set(symbol, "error", 0, f"Couldn't create the wallet: {e}")


# ---- the official tool ---------------------------------------------------------------------------

def find_rpc(symbol: str) -> Path | None:
    found = sorted((TOOLS / symbol).rglob("*wallet-rpc*.exe")) if (TOOLS / symbol).exists() else []
    return found[0] if found else None


def release(symbol: str) -> dict:
    """The official download for this coin: url, file name, size and published SHA-256 (or None)."""
    src = SOURCES[symbol]
    rel = market.fetch_json(f"https://api.github.com/repos/{src['repo']}/releases/latest")
    tag = rel.get("tag_name") or ""
    if "url" in src:
        url, size = src["url"].format(tag=tag), None
        name = url.rsplit("/", 1)[1]
    else:
        asset = next((a for a in rel.get("assets", []) if re.search(src["asset"], a["name"])), None)
        if not asset:
            raise WalletError(f"The latest official {symbol} release has no Windows wallet download.")
        url, name, size = asset["browser_download_url"], asset["name"], asset.get("size")
    allowed = (f"https://github.com/{src['repo']}/releases/download/", "https://downloads.getmonero.org/")
    if not url.startswith(allowed):
        raise WalletError("The wallet download points somewhere unexpected, so MINTRO stopped.")

    sums = None
    if src.get("sums_in_notes"):
        sums = rel.get("body") or ""
    elif src.get("sums_url"):
        sums = _download(src["sums_url"], limit=1_000_000).decode("utf-8", "replace")
    elif src.get("sums_asset"):
        a = next((a for a in rel.get("assets", []) if re.search(src["sums_asset"], a["name"])), None)
        sums = _download(a["browser_download_url"], limit=1_000_000).decode("utf-8", "replace") if a else None
    sha256 = _hash_for(sums, name) if sums is not None else None
    if sums is not None and not sha256:
        raise WalletError(f"{symbol}'s published checksums don't cover this download, so MINTRO stopped.")
    return {"url": url, "name": name, "size": size, "sha256": sha256, "version": tag}


def install(symbol: str, report) -> Path:
    rpc = find_rpc(symbol)
    if rpc:
        return rpc
    report("downloading", 0, f"Finding the official {symbol} wallet…")
    rel = release(symbol)
    TOOLS.mkdir(parents=True, exist_ok=True)
    part = TOOLS / f"{symbol}.zip.part"
    size_text = f" ({rel['size'] / 1e6:.0f} MB)" if rel["size"] else ""
    digest = hashlib.sha256()
    req = urllib.request.Request(rel["url"], headers={"User-Agent": market.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = rel["size"] or int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            pct = done / total * 80 if total else 40
            report("downloading", pct, f"Downloading the official {symbol} wallet{size_text}… {done / 1e6:.0f} MB")
    if rel["sha256"] and digest.hexdigest() != rel["sha256"]:
        part.unlink(missing_ok=True)
        raise WalletError("The download didn't match the fingerprint its developers published, so it was deleted.")
    report("extracting", 85, "Unpacking…")
    dest = (TOOLS / symbol).resolve()
    try:
        with zipfile.ZipFile(part) as z:
            names = z.namelist()
            rpc_member = next((m for m in names if re.search(r"wallet-rpc[^/]*\.exe$", m, re.I)), None)
            if not rpc_member:
                raise WalletError(f"The official {symbol} download doesn't include its wallet-rpc tool.")
            # Only the wallet tool and its support files; skip the node and the interactive wallet
            folder = rpc_member.rpartition("/")[0]
            members = [m for m in names if m == rpc_member or (m.rpartition("/")[0] == folder
                                                               and not m.lower().endswith(".exe") and not m.endswith("/"))]
            for member in members:
                target = (dest / member).resolve()
                if dest not in target.parents:
                    raise WalletError("The wallet archive contains unsafe paths, so MINTRO stopped.")
            z.extractall(dest, members=members)
    finally:
        part.unlink(missing_ok=True)
    store.save(f"tool-{symbol}.json", {"version": rel["version"], "file": rel["name"],
                                       "sha256_checked": bool(rel["sha256"]), "installed": time.time()})
    rpc = find_rpc(symbol)
    if not rpc:
        raise WalletError(f"The official {symbol} download doesn't include its wallet-rpc tool.")
    return rpc


# ---- making the wallet ---------------------------------------------------------------------------

def create_wallet(symbol: str, coin: dict, rpc_exe: Path, report) -> dict:
    folder = WALLETS / symbol
    name = f"mintro-{symbol.lower()}"
    if (folder / f"{name}.keys").exists() or created(symbol):
        raise WalletError("MINTRO already made a wallet for this coin; it never overwrites one.")
    folder.mkdir(parents=True, exist_ok=True)
    report("creating", 90, f"Creating your {coin['name']} wallet…")

    with _WalletRpc(rpc_exe, folder) as rpc:
        temp = f"{name}-new"
        rpc.call("create_wallet", {"filename": temp, "password": "", "language": "English"})
        seed = rpc.call("query_key", {"key_type": "mnemonic"})["key"]
        rpc.call("close_wallet")
        # Re-create it from its own seed so the wallet starts scanning at today's block height:
        # a fresh offline wallet only guesses the height, and a guess that's too high would hide payouts.
        height = max(0, int(coin.get("height") or 0) - RESTORE_MARGIN)
        try:
            rpc.call("restore_deterministic_wallet", {"filename": name, "seed": seed, "restore_height": height,
                                                       "password": "", "language": "English", "autosave_current": True})
            _remove_wallet_files(folder, temp)
        except WalletError:
            log.warning("%s wallet-rpc can't restore from seed; keeping the new wallet as is", symbol)
            for suffix in ("", ".keys", ".address.txt"):
                if (folder / f"{temp}{suffix}").exists():
                    os.replace(folder / f"{temp}{suffix}", folder / f"{name}{suffix}")
            rpc.call("open_wallet", {"filename": name, "password": ""})
            height = 0  # unknown: scanning from the start is the safe instruction
        address = rpc.call("get_address", {"account_index": 0})["address"]
        rpc.call("close_wallet")

    if not basket.valid_address(address):
        raise WalletError("The wallet tool returned an address MINTRO doesn't recognise, so it wasn't used.")
    info = {"symbol": symbol, "name": coin["name"], "address": address, "seed": seed, "restore_height": height,
            "wallet_file": str(folder / name), "backup_file": str(folder / f"BACKUP-{symbol}-KEEP-SECRET.txt"),
            "wallet_page": coin.get("links", {}).get("wallet") or coin.get("links", {}).get("site", ""),
            "created": time.strftime("%Y-%m-%d %H:%M")}
    Path(info["backup_file"]).write_text(_backup_text(info), encoding="utf-8")
    (folder / "backup.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


class _WalletRpc:
    """The coin's wallet-rpc, offline, on a random local port with a random digest login."""

    running: set = set()  # live instances, so MINTRO can stop them when it quits

    def __init__(self, exe: Path, folder: Path):
        self.exe, self.folder = exe, folder
        self.port, self.password = _free_port(), secrets.token_hex(16)
        self.proc: subprocess.Popen | None = None
        self._conn: http.client.HTTPConnection | None = None
        self._nonce = self._realm = None
        self._nc = 0

    def __enter__(self):
        _WalletRpc.running.add(self)
        for offline in (True, False):  # very old forks lack --offline
            self._start(offline)
            if self._wait_ready():
                return self
            output = self._stop(read=True)
            if not offline or not re.search(r"unrecogni[sz]ed|unknown option", output, re.I):
                raise WalletError(f"The wallet tool didn't start. {output.strip().splitlines()[-1][:160] if output.strip() else ''}")
        raise WalletError("The wallet tool didn't start.")

    def __exit__(self, *exc):
        try:
            self.call("stop_wallet", timeout=10)
        except Exception:
            pass
        self._stop()
        _WalletRpc.running.discard(self)

    def _start(self, offline: bool) -> None:
        args = [str(self.exe), "--rpc-bind-ip", "127.0.0.1", "--rpc-bind-port", str(self.port),
                "--rpc-login", f"mintro:{self.password}", "--wallet-dir", str(self.folder),
                "--log-file", str(self.folder / "wallet-rpc.log")]
        if offline:
            args.append("--offline")
        else:
            args += ["--daemon-address", "127.0.0.1:1"]  # nothing listens there: stay effectively offline
        # Console output goes to a file: an unread pipe can fill up and freeze the tool
        self.out_path = self.folder / "wallet-rpc.out"
        with open(self.out_path, "wb") as out:
            self.proc = subprocess.Popen(args, cwd=self.exe.parent, stdout=out, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, creationflags=hardware.NO_WINDOW)

    def _wait_ready(self) -> bool:
        deadline = time.time() + RPC_START_S
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                self.call("get_version", timeout=3)
                return True
            except (WalletError, OSError, http.client.HTTPException):
                time.sleep(0.5)
        return False

    def _stop(self, read: bool = False) -> str:
        proc, self.proc = self.proc, None
        if self._conn:
            self._conn.close()
            self._conn = None
        if not proc:
            return ""
        if proc.poll() is None:
            try:
                proc.wait(8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
        if not read:
            return ""
        try:
            return self.out_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            return ""

    def call(self, method: str, params: dict | None = None, timeout: float = 120) -> dict:
        """JSON-RPC with HTTP digest login on one kept-open connection.

        Monero-family wallet-rpc ties its login nonce to the connection, so the usual "401, then retry on
        a new connection" (urllib's digest handler) is always rejected as stale.
        """
        body = json.dumps({"jsonrpc": "2.0", "id": "0", "method": method, "params": params or {}})
        for attempt in range(3):
            if self._conn is None:
                self._conn, self._nonce = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout), None
            self._conn.timeout = timeout
            headers = {"Content-Type": "application/json"}
            if self._nonce:
                headers["Authorization"] = self._digest()
            try:
                self._conn.request("POST", "/json_rpc", body, headers)
                resp = self._conn.getresponse()
                data = resp.read()
            except (OSError, http.client.HTTPException):
                self._conn.close()
                self._conn = None
                if attempt == 2:
                    raise
                continue
            if resp.status == 401:
                challenge = next((h for h in resp.headers.get_all("WWW-Authenticate") or []
                                  if re.search(r"algorithm=MD5(,|$)", h)), "")
                fields = dict(re.findall(r'(\w+)="?([^",]+)"?', challenge))
                if "nonce" not in fields:
                    raise WalletError("The wallet tool refused MINTRO's login.")
                self._nonce, self._realm, self._nc = fields["nonce"], fields.get("realm", ""), 0
                continue
            if resp.status != 200:
                raise WalletError(f"wallet-rpc answered {resp.status} to {method}")
            result = json.loads(data)
            if "error" in result:
                raise WalletError(result["error"].get("message") or f"{method} failed")
            return result.get("result") or {}
        raise WalletError("The wallet tool refused MINTRO's login.")

    def _digest(self) -> str:
        md5 = lambda s: hashlib.md5(s.encode()).hexdigest()
        self._nc += 1
        nc, cnonce = f"{self._nc:08x}", secrets.token_hex(8)
        ha1, ha2 = md5(f"mintro:{self._realm}:{self.password}"), md5("POST:/json_rpc")
        response = md5(f"{ha1}:{self._nonce}:{nc}:{cnonce}:auth:{ha2}")
        return (f'Digest username="mintro",realm="{self._realm}",nonce="{self._nonce}",uri="/json_rpc",'
                f'algorithm=MD5,response="{response}",qop=auth,nc={nc},cnonce="{cnonce}"')


def _remove_wallet_files(folder: Path, name: str) -> None:
    for suffix in ("", ".keys", ".address.txt"):
        (folder / f"{name}{suffix}").unlink(missing_ok=True)


def _backup_text(info: dict) -> str:
    height = (f"{info['restore_height']}" if info["restore_height"]
              else "0 (scan from the beginning)")
    return f"""MINTRO wallet backup: {info['name']} ({info['symbol']})
KEEP THIS SECRET. Anyone who has these seed words can spend these coins.
Write the seed words on paper. If this laptop is lost, the seed words are the only way back to the coins.

Receive address (MINTRO mines to this):
{info['address']}

Seed words:
{info['seed']}

Restore height: {height}
Wallet file:    {info['wallet_file']}   (no password; you can set one in the wallet app)
Created:        {info['created']}

To see your balance or send coins:
  1. Install the official {info['name']} wallet: {info['wallet_page']}
  2. Open the wallet file above, or choose "restore from seed" and enter the seed words and restore height.
"""


def _hash_for(text: str, filename: str) -> str | None:
    for line in text.splitlines():
        if filename in line and (m := re.search(r"\b([0-9a-fA-F]{64})\b", line)):
            return m.group(1).lower()
    return None


def _download(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": market.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise WalletError("A checksum file was unexpectedly large, so MINTRO stopped.")
    return data


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
