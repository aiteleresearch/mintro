"""Extras: tax report, alerts and "My PCs".

My PCs needs no server: once you pick a shared folder (OneDrive, or any synced or network folder), every PC
writes a small status file into it and the card shows all of them. It's off until a folder is chosen.
"""
from __future__ import annotations

import collections
import csv
import json
import os
import socket
import subprocess
import time
from pathlib import Path

from . import hardware, store

# ---- tax report ------------------------------------------------------------------------------------------


def documents() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents" / "MINTRO"


def tax_report(names: dict) -> Path:
    """CSV of everything mined per day and coin, with the dollar value at the time it was mined."""
    rows = []
    for lane in ("", "-gpu"):
        for day, coins in (store.load(f"daily{lane}.json") or {}).items():
            for symbol, rec in coins.items():
                rows.append((day, symbol, names.get(symbol, symbol), rec["coins"],
                             rec["usd"] if rec.get("priced") else None))
    rows.sort()
    folder = documents()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"MINTRO-mined-{time.strftime('%Y-%m-%d')}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "coin", "name", "amount mined (estimate)", "value in USD when mined", "note"])
        for day, symbol, name, amount, usd in rows:
            w.writerow([day, symbol, name, f"{amount:.8f}", "" if usd is None else f"{usd:.4f}",
                        "" if usd is not None else "no market price at the time"])
        w.writerow([])
        w.writerow(["Amounts are MINTRO's estimates from your speed and the network; the pool's payouts to your "
                    "wallet are the official record. Not tax advice."])
    return path


# ---- alerts ----------------------------------------------------------------------------------------------

_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:MINTRO_T1)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:MINTRO_T2)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


class Alerts:
    """Each alert fires once (remembered in data\\alerts.json) and shows as a Windows notification."""

    def __init__(self):
        saved = store.load("alerts.json") or {}
        self.sent: set = set(saved.get("sent", []))
        self.known_coins: set | None = set(saved["known"]) if "known" in saved else None
        self.recent = collections.deque(saved.get("recent", []), maxlen=20)

    def check(self, snap: dict) -> None:
        day = time.strftime("%Y-%m-%d")
        if snap.get("state") == "blocked":
            self._fire(f"blocked:{day}", "MINTRO stopped", snap.get("message", "")[:200])
        symbols = {e["symbol"] for e in snap.get("entries", [])}
        if self.known_coins is None:
            self.known_coins = symbols  # first run: nothing is "new"
        for e in snap.get("entries", []):
            sym, mined = e["symbol"], e.get("mined") or 0
            if e.get("min_payout") and mined >= e["min_payout"]:
                self._fire(f"payout:{sym}:{int(mined // e['min_payout'])}", f"{e['name']} ready for a payout",
                           f"About {mined:.4g} {sym} mined: enough for the pool's minimum payout.")
            if mined and (e.get("change24") or 0) >= 25:
                self._fire(f"price:{sym}:{day}", f"{e['name']} is up {e['change24']:.0f}% today",
                           f"You've mined about {mined:.4g} {sym}.")
        for sym in sorted(symbols - self.known_coins):
            name = next((e["name"] for e in snap["entries"] if e["symbol"] == sym), sym)
            self._fire(f"new:{sym}", "New coin in MINTRO", f"{name} ({sym}) can now be mined.")
        self.known_coins |= symbols
        self._save()

    def _fire(self, key: str, title: str, text: str) -> None:
        if key in self.sent:
            return
        self.sent.add(key)
        self.recent.appendleft({"at": time.time(), "title": title, "text": text})
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
                             env={**os.environ, "MINTRO_T1": title, "MINTRO_T2": text},
                             creationflags=hardware.NO_WINDOW)
        except OSError:
            pass

    def _save(self) -> None:
        store.save("alerts.json", {"sent": sorted(self.sent)[-500:], "known": sorted(self.known_coins or []),
                                   "recent": list(self.recent)})


# ---- My PCs ----------------------------------------------------------------------------------------------


def default_fleet_folder() -> str:
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    return str(Path(onedrive) / "MINTRO PCs") if onedrive else ""


def fleet_folder() -> Path | None:
    folder = (store.load("app-prefs.json") or {}).get("fleet_folder", "")
    return Path(folder) if folder else None


def publish(snap: dict) -> None:
    """Write this PC's status into the shared folder."""
    folder = fleet_folder()
    if not folder:
        return
    t = snap.get("tuning") or {}
    me = {"pc": socket.gethostname(), "tier": t.get("tier"), "cpu": t.get("cpu"), "state": snap.get("state"),
          "coin": (snap.get("current") or {}).get("name"), "hashrate": snap.get("hashrate", 0),
          "gpu": snap.get("gpu"), "mined_value": snap.get("total_value", 0), "currency": snap.get("currency"),
          "updated": time.time()}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{me['pc']}.json").write_text(json.dumps(me), encoding="utf-8")
    except OSError:
        pass


def fleet() -> list[dict]:
    folder = fleet_folder()
    pcs = []
    for f in sorted(folder.glob("*.json")) if folder and folder.exists() else []:
        try:
            pc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pc["online"] = time.time() - pc.get("updated", 0) < 300
        pcs.append(pc)
    return pcs
