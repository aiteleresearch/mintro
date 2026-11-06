"""Automatic updates that never stop the miner.

1. A few minutes after start, then every few hours, MINTRO asks MINTRO's website for the latest release
   (config.UPDATE_FEED), falling back to GitHub's latest release of config.GITHUB_REPO; the feed in
   app-prefs.json "update_feed" (a beta channel) replaces both.
2. If it's newer, MINTRO downloads MINTRO-Update-<version>.zip and its .sig, and checks the signature against
   the publisher key in signing.py. An update that isn't signed by the publisher is never installed.
3. It unpacks the new version next to the installed one (%LOCALAPPDATA%\\Programs\\MINTRO-update-<version>).
4. Once nobody has touched the PC for a couple of minutes, the engines hand the running miners over (they keep
   mining, see Engine.detach) and MINTRO exits. A small PowerShell helper swaps the program folder, starts the
   new version, which adopts the miners, and puts the old version back if the new one doesn't report healthy.

Earnings, speeds, settings and wallets live in %LOCALAPPDATA%\\MINTRO, which an update never touches, so
everything carries on from where it was. Only the installed app updates itself; running from source doesn't.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import __version__, config, installer, market, signing, store, tuning

log = logging.getLogger("mintro.updater")

FIRST_CHECK_S = 3 * 60
CHECK_EVERY_S = 6 * 3600
IDLE_TO_APPLY_S = 120        # install when nobody has used the PC for this long
MAX_DOWNLOAD = 300 * 1024 * 1024
HEALTHY_FILE = "update-ok.json"
PENDING_FILE = "update-pending.json"
FAILED_FILE = "update-failed.json"   # versions that didn't start on this PC: skipped until a newer one comes
# CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW. Not DETACHED_PROCESS: PowerShell without a console dies silently.
NEW_PROCESS = 0x00000200 | 0x08000000
HELPER_START_S = 20    # the helper must say it's running within this long, or MINTRO stays open

# The helper runs after MINTRO has exited: it swaps the folders, starts the new version and waits for it to
# say it's healthy (HEALTHY_FILE with the new version). If it doesn't within 90 s, the old version comes back.
HELPER = r"""
param([int]$OldPid, [string]$App, [string]$Staged, [string]$Version, [string]$Ok, [string]$Log)
function Note($m) { Add-Content -LiteralPath $Log -Value ("{0:u} {1}" -f (Get-Date), $m) }
$Leaf = Split-Path $App -Leaf
$Old = "$App.old"
Note "updating to $Version; waiting for MINTRO to close"
try { Wait-Process -Id $OldPid -Timeout 60 -ErrorAction Stop } catch {}
Stop-Process -Id $OldPid -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $Old) { Remove-Item -LiteralPath $Old -Recurse -Force -ErrorAction SilentlyContinue }
$moved = $false
for ($i = 0; $i -lt 40 -and -not $moved; $i++) {
  try { Rename-Item -LiteralPath $App -NewName "$Leaf.old" -ErrorAction Stop; $moved = $true } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $moved) {
  Note "the program folder is in use; staying on the current version for now"
  Start-Process -FilePath (Join-Path $App 'MINTRO.exe')
  exit 1
}
Rename-Item -LiteralPath $Staged -NewName $Leaf
Remove-Item -LiteralPath $Ok -ErrorAction SilentlyContinue
Start-Process -FilePath (Join-Path $App 'MINTRO.exe')
for ($i = 0; $i -lt 90; $i++) {
  Start-Sleep -Seconds 1
  if ((Test-Path -LiteralPath $Ok) -and ((Get-Content -LiteralPath $Ok -Raw) -match [regex]::Escape('"' + $Version + '"'))) {
    Note "MINTRO $Version is running"
    Remove-Item -LiteralPath $Old -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
  }
}
Note "MINTRO $Version didn't start properly; going back to the previous version"
Get-Process MINTRO -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$App\*" } | Stop-Process -Force
Start-Sleep -Seconds 2
Rename-Item -LiteralPath $App -NewName "$Leaf.failed-$Version" -ErrorAction SilentlyContinue
Rename-Item -LiteralPath $Old -NewName $Leaf
Start-Process -FilePath (Join-Path $App 'MINTRO.exe')
exit 2
"""


def parse_version(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:3]) or (0,)


def signed_message(version: str, sha256: str) -> bytes:
    """What the publisher signs for an update (publisher/mintro_keys.py sign-update)."""
    return f"MINTRO update {version} {sha256}".encode()


def verify_signature(sig: dict, version: str, sha256: str) -> bool:
    try:
        signature = base64.urlsafe_b64decode(sig["signature"] + "=" * (-len(sig["signature"]) % 4))
        return (sig.get("version") == version and sig.get("sha256") == sha256
                and signing.verify(bytes.fromhex(signing.PUBLIC_KEY_HEX), signed_message(version, sha256), signature))
    except Exception:
        return False


def installed() -> bool:
    """True for the installed app (the only kind that updates itself)."""
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).resolve().parent == installer.APP_DIR.resolve()


def feed_urls() -> list[str]:
    """Where to look for a newer release, in order; the first that answers is used."""
    prefs = store.load("app-prefs.json") or {}
    if prefs.get("update_feed"):
        return [prefs["update_feed"]]
    urls = [config.UPDATE_FEED] if getattr(config, "UPDATE_FEED", "") else []
    if config.GITHUB_REPO:
        urls.append(f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest")
    return urls


def feed_url() -> str:
    urls = feed_urls()
    return urls[0] if urls else ""


def latest_release() -> dict:
    """The newest release from the first update source that answers."""
    error: Exception | None = None
    for url in feed_urls():
        try:
            return market.fetch_json(url)
        except Exception as e:
            log.info("update source %s didn't answer: %s", url, e)
            error = e
    raise error or RuntimeError("No update source is set.")


class Updater:
    def __init__(self):
        self.state, self.message, self.available = "idle", "", None
        self._staged: Path | None = None
        self._lock = threading.Lock()
        pending = store.load(PENDING_FILE) or {}
        # Just restarted after an update: say so once on the card
        self.just_updated = pending.get("from") if pending.get("to") == __version__ else None
        if pending.get("to") and pending["to"] != __version__ and pending.get("from") == __version__:
            # The helper put this version back because the new one didn't start: don't try that one again
            failed = store.load(FAILED_FILE) or {}
            failed[pending["to"]] = time.time()
            store.save(FAILED_FILE, failed)
            store.save(PENDING_FILE, {})
            log.warning("update to %s didn't start on this PC; staying on %s until a newer version", pending["to"], __version__)
        if not installed():
            self.state, self.message = "off", "Updates are installed by the installed app."
        elif not feed_url():
            self.state, self.message = "off", "No update source is set."

    def status(self) -> dict:
        return {"version": __version__, "state": self.state, "message": self.message, "available": self.available,
                "just_updated": self.just_updated}

    def run(self, apply_update) -> None:
        """Background loop. apply_update() hands the miners over and closes MINTRO once the helper is running."""
        if self.state == "off":
            return
        time.sleep(FIRST_CHECK_S)
        next_check = 0.0
        while True:
            try:
                if self.state != "ready" and time.time() >= next_check:
                    next_check = time.time() + CHECK_EVERY_S
                    self.check()
                if self.state == "ready" and tuning.idle_seconds() >= IDLE_TO_APPLY_S:
                    self.state, self.message = "applying", f"Installing {self.available}…"
                    if self.launch_helper():
                        apply_update()
                        return
                    next_check = time.time() + 3600  # the helper didn't start: try again in an hour
            except Exception as e:
                log.exception("update check failed")
                self.state, self.message = "error", str(e)
            time.sleep(30)

    def check_safely(self) -> None:
        if self.state in ("off", "checking", "downloading", "applying"):
            return
        try:
            self.check()
        except Exception as e:
            log.exception("update check failed")
            self.state, self.message = "error", str(e)

    def install_now(self, apply_update) -> bool:
        """The person pressed Install now: same handover as the automatic install, without waiting for idle."""
        if self.state != "ready" or not self.launch_helper():
            return False
        self.state, self.message = "applying", f"Installing {self.available}…"
        apply_update()
        return True

    def check(self) -> None:
        """Look for a newer release; download, verify and unpack it if there is one."""
        with self._lock:
            self.state, self.message = "checking", ""
            release = latest_release()
            version = str(release.get("tag_name", "")).lstrip("vV")
            if parse_version(version) <= parse_version(__version__):
                self.state, self.message, self.available = "idle", "Up to date", None
                return
            if version in (store.load(FAILED_FILE) or {}):
                self.state, self.available = "idle", None
                self.message = f"{version} didn't start on this PC, so MINTRO stayed on {__version__}"
                return
            assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
            name = f"MINTRO-Update-{version}.zip"
            if name not in assets or f"{name}.sig" not in assets:
                self.state, self.message = "idle", f"{version} has no update package"
                return
            staged = installer.APP_DIR.with_name(f"MINTRO-update-{version}")
            if (staged / "MINTRO.exe").exists() and (staged / ".verified").exists():
                self._staged, self.available, self.state = staged, version, "ready"
                return
            self.state, self.available, self.message = "downloading", version, f"Downloading {version}…"
            sig = json.loads(_download(assets[f"{name}.sig"], limit=64 * 1024))
            zip_path = _updates_dir() / name
            digest = _download_to(assets[name], zip_path)
            if not verify_signature(sig, version, digest):
                zip_path.unlink(missing_ok=True)
                raise RuntimeError(f"The {version} update isn't signed by MINTRO's publisher; it was not installed.")
            shutil.rmtree(staged, ignore_errors=True)
            _extract(zip_path, staged)
            if not (staged / "MINTRO.exe").exists():
                raise RuntimeError("The update package has no MINTRO.exe.")
            (staged / ".verified").write_text(digest)
            zip_path.unlink(missing_ok=True)
            self._staged, self.state = staged, "ready"
            self.message = f"MINTRO {version} is ready. It installs when you step away; mining keeps going."
            log.info("update %s downloaded and verified", version)

    def launch_helper(self) -> bool:
        if not self._staged or not self._staged.exists():
            self.state = "idle"
            return False
        folder = _updates_dir()
        script = folder / "apply-update.ps1"
        script.write_text(HELPER, encoding="utf-8")
        store.save(PENDING_FILE, {"from": __version__, "to": self.available, "at": time.time()})
        (store.DATA / HEALTHY_FILE).unlink(missing_ok=True)
        log_file = folder / "update.log"
        seen = log_file.stat().st_size if log_file.exists() else 0
        args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-OldPid", str(os.getpid()), "-App", str(installer.APP_DIR),
                "-Staged", str(self._staged), "-Version", self.available,
                "-Ok", str(store.DATA / HEALTHY_FILE), "-Log", str(log_file)]
        try:
            helper = subprocess.Popen(args, creationflags=NEW_PROCESS, close_fds=True, cwd=str(folder))
        except OSError as e:
            log.warning("couldn't start the update helper: %s", e)
            self.state, self.message = "error", "Couldn't start the update installer."
            return False
        # MINTRO only closes once the helper has written its first line: if it never runs, nobody is left
        # without MINTRO
        deadline = time.time() + HELPER_START_S
        while time.time() < deadline and helper.poll() is None:
            if log_file.exists() and f"updating to {self.available}" in log_file.read_bytes()[seen:].decode("utf-8", "replace"):
                log.info("installing %s; handing the miners over", self.available)
                return True
            time.sleep(0.25)
        if helper.poll() is None:
            helper.kill()
        log.warning("the update helper didn't start (exit code %s); staying on %s", helper.poll(), __version__)
        store.save(PENDING_FILE, {})
        self.state, self.message = "error", "The update installer didn't start. MINTRO will try again later."
        return False


def mark_healthy() -> None:
    """Called once the card is up: tells the update helper this version works, and tidies up after an update."""
    store.save(HEALTHY_FILE, {"version": __version__, "at": time.time()})
    pending = store.load(PENDING_FILE) or {}
    if pending and pending.get("to") == __version__:
        store.save(PENDING_FILE, {})
        if installed():
            installer.set_version(__version__)
    for lane in ("", "-gpu"):
        store.save(f"handoff{lane}.json", {})  # adopted (or not needed): a later start mustn't pick it up again
    for leftover in installer.APP_DIR.parent.glob("MINTRO.failed-*"):
        shutil.rmtree(leftover, ignore_errors=True)


def _updates_dir() -> Path:
    folder = store.DATA / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _download(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": market.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Download is larger than expected.")
    return data


def _download_to(url: str, path: Path) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": market.USER_AGENT})
    h, size = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as out:
        while chunk := r.read(1 << 20):
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise RuntimeError("Update download is larger than expected.")
            h.update(chunk)
            out.write(chunk)
    return h.hexdigest()


def _extract(zip_path: Path, target: Path) -> None:
    root = target.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            dest = (root / member.filename).resolve()
            if root not in dest.parents and dest != root:
                raise RuntimeError("The update package contains an unsafe path.")
        z.extractall(root)
