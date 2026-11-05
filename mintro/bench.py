"""Measure real RandomX speed with XMRig's offline benchmark.

XMRig is fetched from its official GitHub release and checked against the release's SHA-256 list
before anything is extracted. The benchmark never connects to a pool.
"""
from __future__ import annotations

import collections
import hashlib
import io
import logging
import os
import platform
import queue
import re
import statistics
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import hardware, market, store

log = logging.getLogger("mintro.bench")

RELEASE_API = "https://api.github.com/repos/xmrig/xmrig/releases/latest"
DOWNLOAD_PREFIX = "https://github.com/xmrig/xmrig/releases/download/"
MEASURE_S = 60   # steady-state sampling after the first speed report
TIMEOUT_S = 360  # dataset init can be slow when RAM is tight

SPEED = re.compile(r"speed 10s/60s/15m\s+(\S+)\s+(\S+)\s+(\S+)\s+H/s")
HUGE = re.compile(r"huge pages\s+(\d+)%")
READY = re.compile(r"READY threads\s+(\d+)/(\d+)")
FINISHED = re.compile(r"benchmark finished in [\d.]+ seconds \(([\d.]+) h/s\)")

BUSY = ("starting", "downloading", "verifying", "warming", "measuring")


class BenchError(Exception):
    """A failure with a message meant for the user."""


def load_result(cpu: str) -> dict | None:
    """The saved benchmark, if it was taken on this CPU."""
    b = store.load("bench.json")
    return b if b and b.get("cpu") == cpu and b.get("rx_hps") else None


def find_xmrig() -> Path | None:
    exe = "xmrig.exe" if os.name == "nt" else "xmrig"
    found = sorted(store.MINERS.rglob(exe)) if store.MINERS.exists() else []
    return found[-1] if found else None


class Job:
    """One benchmark at a time on a background thread; the page polls status()."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"state": "idle"}
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, hw: dict) -> dict:
        with self._lock:
            if not self.running():
                self._state = {"state": "starting", "progress": 0, "message": "Getting ready…"}
                self._thread = threading.Thread(target=self._run, args=(hw,), daemon=True)
                self._thread.start()
            return dict(self._state)

    def stop(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            proc.kill()

    def _set(self, state: str, progress: float, message: str, **extra) -> None:
        with self._lock:
            self._state = {"state": state, "progress": round(progress), "message": message, **extra}

    def _run(self, hw: dict) -> None:
        try:
            exe = find_xmrig() or install(self._set)
            result = self._benchmark(exe, hw)
            store.save("bench.json", result)
            self._set("done", 100, f"Measured {result['rx_hps']:,.0f} H/s", result=result)
        except BenchError as e:
            self._set("error", 0, str(e))
        except Exception as e:  # unexpected: keep the details in the log
            log.exception("benchmark failed")
            self._set("error", 0, f"Speed test failed: {e}")
        finally:
            self._proc = None

    def _benchmark(self, exe: Path, hw: dict) -> dict:
        self._set("starting", 5, "Starting XMRig and preparing 2 GB of RandomX data…")
        try:
            proc = subprocess.Popen(
                [str(exe), "--bench=1M", "--no-color", "--print-time=5"],
                cwd=exe.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=hardware.NO_WINDOW,
            )
        except OSError as e:
            raise BenchError(f"Windows refused to start XMRig ({e.strerror or e}). Antivirus software often blocks miners.") from e
        self._proc = proc
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True).start()

        on_battery = hw.get("laptop") and not hw.get("on_ac", True)
        tail = collections.deque(maxlen=20)
        samples: list[float] = []
        watts: list[float] = []
        huge, threads, finished = 0, None, None
        t0, measuring_since, next_power = time.time(), None, 0.0
        try:
            while True:
                now = time.time()
                if now - t0 > TIMEOUT_S:
                    raise BenchError("XMRig took too long to report a speed. Close other apps to free memory and try again.")
                try:
                    line = lines.get(timeout=1)
                except queue.Empty:
                    line = ""
                if line is None:  # XMRig exited
                    break
                if line:
                    tail.append(line.rstrip())
                    if m := HUGE.search(line):
                        huge = int(m.group(1))
                    if m := READY.search(line):
                        threads = int(m.group(1))
                    if m := FINISHED.search(line):
                        finished = float(m.group(1))
                        break
                    if "dataset ready" in line and measuring_since is None:
                        self._set("warming", 25, "Warming up…")
                    if m := SPEED.search(line):
                        value = _num(m.group(1))
                        if value and measuring_since is None:
                            measuring_since = now  # first 10 s average includes ramp-up: skip it
                        elif value:
                            samples.append(value)
                if measuring_since:
                    elapsed = now - measuring_since
                    current = f" {samples[-1]:,.0f} H/s" if samples else ""
                    self._set("measuring", 30 + 70 * min(elapsed / MEASURE_S, 1), f"Measuring…{current}")
                    if on_battery and now >= next_power:
                        if (w := hardware.battery_watts()) is not None:
                            watts.append(w)
                        next_power = now + 5
                    if elapsed >= MEASURE_S and len(samples) >= 3:
                        break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        hps = finished or (statistics.median(samples) if samples else None)
        if not hps:
            raise BenchError(_explain_failure(list(tail)))
        return {
            "cpu": hw["cpu"],
            "rx_hps": round(hps, 1),
            "huge_pages_pct": huge,
            "threads": threads,
            "watts": round(statistics.median(watts), 1) if len(watts) >= 3 else None,
            "measured_at": time.time(),
            "miner": exe.parent.name,
        }


def install(set_state) -> Path:
    """Download the latest official XMRig build for this OS, verify its SHA-256, extract into miners/."""
    set_state("downloading", 0, "Finding the latest XMRig release…")
    release = market.fetch_json(RELEASE_API)
    assets = {a["name"]: a for a in release.get("assets", [])}
    suffix = _asset_suffix()
    name = next((n for n in assets if n.endswith("-" + suffix)), None)
    sums = assets.get("SHA256SUMS")
    if not name or not sums:
        raise BenchError("Couldn't find an XMRig download for this system.")
    url, sums_url = assets[name]["browser_download_url"], sums["browser_download_url"]
    if not (url.startswith(DOWNLOAD_PREFIX) and sums_url.startswith(DOWNLOAD_PREFIX)):
        raise BenchError("XMRig's download points somewhere unexpected, so MINTRO stopped.")
    expected = re.search(rf"^([0-9a-f]{{64}})\s+\*?{re.escape(name)}\s*$", _download(sums_url).decode(), re.M)
    if not expected:
        raise BenchError("XMRig's checksum list doesn't cover this download, so MINTRO stopped.")

    set_state("downloading", 2, f"Downloading XMRig {release.get('tag_name', '')} "
                                f"({assets[name].get('size', 0) / 1e6:.1f} MB) from github.com/xmrig…")
    blob = _download(url)
    set_state("verifying", 4, "Checking the download's SHA-256 fingerprint…")
    if hashlib.sha256(blob).hexdigest() != expected.group(1):
        raise BenchError("The download didn't match XMRig's published fingerprint and was discarded.")
    _extract(blob, name)
    exe = find_xmrig()
    if not exe:
        raise BenchError("XMRig disappeared right after download, most likely removed by antivirus (it flags all "
                         "miners). You can allow it under Windows Security > Protection history, then try again.")
    return exe


def _asset_suffix() -> str:
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Windows":
        return "windows-arm64.zip" if arm else "windows-x64.zip"
    if system == "Darwin":
        return "macos-arm64.tar.gz" if arm else "macos-x64.tar.gz"
    return "linux-static-x64.tar.gz"


def _download(url: str, limit: int = 50_000_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": market.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise BenchError("The XMRig download was unexpectedly large, so MINTRO stopped.")
    return data


def _extract(blob: bytes, name: str) -> None:
    store.MINERS.mkdir(parents=True, exist_ok=True)
    root = store.MINERS.resolve()

    def check(member: str) -> None:
        dest = (root / member).resolve()
        if dest != root and root not in dest.parents:
            raise BenchError("The XMRig archive contains unsafe paths, so MINTRO stopped.")

    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            # Skip WinRing0x64.sys: XMRig only loads it with admin rights for register tweaks, which MINTRO never uses
            members = [m for m in z.namelist() if not m.lower().endswith(".sys")]
            for member in members:
                check(member)
            z.extractall(root, members=members)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
            members = [m for m in t.getmembers() if m.isfile() or m.isdir()]
            for m in members:
                check(m.name)
            t.extractall(root, members=members, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def _pump(stream, q: queue.Queue) -> None:
    for line in stream:
        q.put(line)
    q.put(None)


def _num(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _explain_failure(tail: list[str]) -> str:
    text = "\n".join(tail).lower()
    if "failed to allocate" in text or "not enough memory" in text:
        return "Not enough free RAM for RandomX (it needs about 2.5 GB). Close some apps and try again."
    if not tail:
        return "XMRig closed without saying anything. Antivirus software may have blocked it."
    return ("XMRig stopped before reporting a speed, most often because antivirus blocked it (it flags every miner; "
            f"see Windows Security > Protection history). Last message: {tail[-1][:160]}")
