"""Mining engines MINTRO can drive: XMRig (RandomX, GhostRider), cpuminer-opt (yespower, yescrypt, minotaurx...)
and SRBMiner-Multi (GPU coins).

Each engine is downloaded from its developers' official GitHub release into %LOCALAPPDATA%\\MINTRO\\miners,
checked against whatever checksum they publish, and then run as a separate process. A driver knows how to
build that engine's command line and read its live speed.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from . import bench, market, store

LOGIN_ERROR = re.compile(r"login error|invalid (?:payment |wallet )?address|invalid wallet|bad wallet|"
                         r"authentication failed|unauthori[sz]ed|invalid user", re.I)
CONNECT_ERROR = re.compile(r"connect(?:ion)? (?:error|failed|refused)|getaddrinfo|ssl|tls|read error|timed out", re.I)
NEW_JOB = re.compile(r"new job|new block|job received|stratum difficulty|accepted", re.I)


class Driver:
    name = ""
    title = ""
    fee_note = ""  # anything the engine itself takes, shown to the person

    def exe(self) -> Path | None:
        raise NotImplementedError

    def install(self, report) -> Path:
        raise NotImplementedError

    def args(self, exe: Path, algo: str, pool: dict, api_port: int, token: str, turn: dict, light: bool) -> list[str]:
        """pool: {host, port, tls, user, password}."""
        raise NotImplementedError

    def poll(self, api_port: int, token: str) -> tuple:
        """(10 s speed, 60 s speed, accepted shares) in H/s; None where unknown."""
        raise NotImplementedError


class Adopted:
    """A miner started by the previous MINTRO (before it updated itself), driven like a subprocess.Popen."""

    _ACCESS = 0x00100000 | 0x0001 | 0x1000 | 0x0200  # SYNCHRONIZE, TERMINATE, QUERY_LIMITED_INFORMATION, SET_INFORMATION

    def __init__(self, pid: int):
        k32 = self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wt.HANDLE
        handle = k32.OpenProcess(self._ACCESS, False, int(pid))
        if not handle:
            raise OSError(ctypes.get_last_error(), f"no process {pid}")
        self._handle, self.pid, self.returncode = handle, int(pid), None

    def image(self) -> str:
        """Full path of the program this process runs (guards against a reused process id)."""
        buf, size = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
        ok = self._k32.QueryFullProcessImageNameW(wt.HANDLE(self._handle), 0, buf, ctypes.byref(size))
        return buf.value if ok else ""

    def poll(self):
        code = wt.DWORD()
        if (self.returncode is None and self._k32.GetExitCodeProcess(wt.HANDLE(self._handle), ctypes.byref(code))
                and code.value != 259):  # STILL_ACTIVE
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout: float | None = None):
        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if self._k32.WaitForSingleObject(wt.HANDLE(self._handle), ms) == 0x102:  # WAIT_TIMEOUT
            raise subprocess.TimeoutExpired("miner", timeout)
        return self.poll()

    def terminate(self) -> None:
        if self.poll() is None:
            self._k32.TerminateProcess(wt.HANDLE(self._handle), 1)

    kill = terminate

    def __del__(self):
        try:
            self._k32.CloseHandle(wt.HANDLE(self._handle))
        except Exception:
            pass


class XMRig(Driver):
    name, title, fee_note = "xmrig", "XMRig", "XMRig mines 1% of the time for its developers (its donation level)."

    def exe(self):
        return bench.find_xmrig()

    def install(self, report):
        return bench.install(lambda _s, pct, msg, **_k: report(pct, msg))

    def args(self, exe, algo, pool, api_port, token, turn, light):
        args = [str(exe), "-a", algo, "-o", f"{pool['host']}:{pool['port']}", "-u", pool["user"], "-p", pool["password"],
                "--http-host", "127.0.0.1", "--http-port", str(api_port), "--http-access-token", token,
                "--no-color", "--donate-level", "1", "--print-time", "30",
                "--cpu-max-threads-hint", str(turn["hint"]), "--cpu-priority", str(turn["priority_arg"]),
                "--retries", "1", "--retry-pause", "5"]
        if light:
            args.append("--randomx-mode=light")  # 256 MB instead of a 2.3 GB dataset when RAM is short
        if pool["tls"]:
            args.append("--tls")
        return args

    def poll(self, api_port, token):
        req = urllib.request.Request(f"http://127.0.0.1:{api_port}/2/summary",
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=1.5) as r:
                data = json.loads(r.read())
        except (OSError, ValueError):
            return None, None, None
        total = (data.get("hashrate") or {}).get("total") or [None, None, None]
        return total[0], total[1], (data.get("results") or {}).get("shares_good")


class CpuMiner(Driver):
    name, title, fee_note = "cpuminer", "cpuminer-opt", ""
    repo, asset = "JayDDee/cpuminer-opt", r"^cpuminer-opt-.*-windows\.zip$"

    def exe(self):
        folder = store.MINERS / self.name
        if not folder.exists():
            return None
        found = {p.name.lower(): p for p in folder.rglob("cpuminer*.exe")}
        for name in self._preferred():
            if name in found:
                return found[name]
        return next(iter(found.values()), None)

    @staticmethod
    def _preferred() -> list[str]:
        """Fastest build this CPU can run safely; a build with unsupported instructions would just crash."""
        avx2 = os.name == "nt" and bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))  # PF_AVX2
        return (["cpuminer-avx2.exe", "cpuminer-avx.exe"] if avx2 else []) + ["cpuminer-sse2.exe"]

    def install(self, report):
        return _install_release(self, report, sums=None)

    def args(self, exe, algo, pool, api_port, token, turn, light):
        scheme = "stratum+tcps" if pool["tls"] else "stratum+tcp"
        return [str(exe), "-a", algo, "-o", f"{scheme}://{pool['host']}:{pool['port']}", "-u", pool["user"],
                "-p", pool["password"], "-t", str(turn["cpu_threads"]), "-b", f"127.0.0.1:{api_port}",
                "--cpu-priority", str(turn["priority_arg"]), "-q"]

    def poll(self, api_port, token):
        try:
            with socket.create_connection(("127.0.0.1", api_port), timeout=1.5) as s:
                s.sendall(b"summary")
                text = s.recv(4096).decode("ascii", "replace")
        except OSError:
            return None, None, None
        fields = dict(part.split("=", 1) for part in text.strip("|\x00\r\n").split(";") if "=" in part)
        try:
            hps = float(fields.get("KHS", 0)) * 1000
            shares = int(fields.get("ACC", 0))
        except ValueError:
            return None, None, None
        return hps or None, hps or None, shares


class SRBMiner(Driver):
    name, title = "srbminer", "SRBMiner-Multi"
    fee_note = "SRBMiner-Multi keeps a small dev fee (about 0.85% on most GPU algorithms)."
    repo, asset, md5 = "doktor83/SRBMiner-Multi", r"^SRBMiner-Multi-.*-win64\.zip$", r"^SRBMiner-Multi-.*-win64\.md5$"

    def exe(self):
        folder = store.MINERS / self.name
        found = sorted(folder.rglob("SRBMiner-MULTI.exe")) if folder.exists() else []
        return found[0] if found else None

    def install(self, report):
        return _install_release(self, report, sums="md5")

    def args(self, exe, algo, pool, api_port, token, turn, light):
        url = f"stratum+ssl://{pool['host']}:{pool['port']}" if pool["tls"] else f"{pool['host']}:{pool['port']}"
        return [str(exe), "--algorithm", algo, "--pool", url, "--wallet", pool["user"],
                "--password", pool["password"], "--disable-cpu", "--api-enable", "--api-port", str(api_port),
                "--api-rig-restricted"]

    def poll(self, api_port, token):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/", timeout=1.5) as r:
                data = json.loads(r.read())
        except (OSError, ValueError):
            return None, None, None
        hps = _find_number(data, ("hashrate",), ("total", "now", "hashrate_total"))
        shares = _find_number(data, ("shares",), ("accepted",))
        return hps, hps, int(shares) if shares is not None else None


DRIVERS = {d.name: d for d in (XMRig(), CpuMiner(), SRBMiner())}


def _find_number(data, parents: tuple, keys: tuple):
    """First number under one of `keys` inside a dict found under one of `parents` (SRBMiner's API nests it)."""
    stack = [(None, data)]
    while stack:
        parent, node = stack.pop()
        if isinstance(node, dict):
            if parent in parents:
                for k in keys:
                    v = node.get(k)
                    if isinstance(v, (int, float)) and v > 0:
                        return float(v)
            stack.extend((k, v) for k, v in node.items())
        elif isinstance(node, list):
            stack.extend((parent, v) for v in node)
    return None


def _install_release(driver, report, sums: str | None) -> Path:
    """Latest Windows build from the engine's official GitHub release, checked and unpacked into miners/<engine>."""
    report(0, f"Finding the latest {driver.title} release…")
    rel = market.fetch_json(f"https://api.github.com/repos/{driver.repo}/releases/latest")
    assets = {a["name"]: a for a in rel.get("assets", [])}
    name = next((n for n in assets if re.search(driver.asset, n)), None)
    if not name:
        raise bench.BenchError(f"Couldn't find a Windows download of {driver.title}.")
    url = assets[name]["browser_download_url"]
    if not url.startswith(f"https://github.com/{driver.repo}/releases/download/"):
        raise bench.BenchError(f"{driver.title}'s download points somewhere unexpected, so MINTRO stopped.")
    report(2, f"Downloading {driver.title} {rel.get('tag_name', '')} ({assets[name].get('size', 0) / 1e6:.0f} MB)…")
    blob = bench._download(url, limit=200_000_000)
    if sums == "md5":
        md5_asset = next((a for n, a in assets.items() if re.search(driver.md5, n)), None)
        text = bench._download(md5_asset["browser_download_url"], limit=100_000).decode("ascii", "replace") if md5_asset else ""
        expected = re.search(r"\b([0-9a-fA-F]{32})\b", text)
        if not expected or hashlib.md5(blob).hexdigest() != expected.group(1).lower():
            raise bench.BenchError(f"The {driver.title} download didn't match its published checksum, so it was discarded.")
    report(80, "Unpacking…")
    root = (store.MINERS / driver.name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        # Skip kernel drivers (.sys): they need admin rights and MINTRO never uses them
        members = [m for m in z.namelist() if not m.lower().endswith(".sys") and not m.endswith("/")]
        for m in members:
            if root not in (root / m).resolve().parents:
                raise bench.BenchError(f"The {driver.title} archive contains unsafe paths, so MINTRO stopped.")
        z.extractall(root, members=members)
    store.save(f"engine-{driver.name}.json", {"version": rel.get("tag_name"), "file": name,
                                              "checksum": "md5" if sums == "md5" else "none published"})
    exe = driver.exe()
    if not exe:
        raise bench.BenchError(f"{driver.title} disappeared right after download, most likely removed by antivirus.")
    return exe
