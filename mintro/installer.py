"""Install and uninstall MINTRO for the current Windows user (no admin rights needed).

Program files go to %LOCALAPPDATA%\\Programs\\MINTRO, with Start menu and desktop shortcuts and an entry in
Settings > Apps. User data (settings, wallets, miners) lives separately in %LOCALAPPDATA%\\MINTRO and is
never removed by the uninstaller.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
import winreg
import zipfile
from pathlib import Path

from . import __version__, store

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / "MINTRO"
EXE = APP_DIR / "MINTRO.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MINTRO"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = 0x00000008  # DETACHED_PROCESS

# Shortcut work goes through Windows' own Shell COM object; paths travel in environment variables, so no
# quoting games and no script files.
_PS_SHORTCUTS = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')) {
  $path = Join-Path $folder 'MINTRO.lnk'
  if ($env:MINTRO_REMOVE) { Remove-Item $path -ErrorAction SilentlyContinue; continue }
  $s = $shell.CreateShortcut($path)
  $s.TargetPath = $env:MINTRO_EXE; $s.WorkingDirectory = $env:MINTRO_DIR
  $s.IconLocation = "$($env:MINTRO_EXE),0"; $s.Description = 'MINTRO: mine a basket of CPU coins'
  $s.Save()
}
"""


def install(payload: Path, progress=lambda pct, text: None) -> Path:
    """Unpack the app, add shortcuts and the Apps entry. Returns the installed MINTRO.exe."""
    progress(2, "Closing MINTRO if it's running…")
    close_running(handoff=True)  # a reinstall over a running MINTRO keeps its miner going, like an update
    progress(8, "Removing the previous version…")
    _remove_tree(APP_DIR)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload) as z:
        members = z.infolist()
        root = APP_DIR.resolve()
        for i, member in enumerate(members):
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError("The installer contains an unsafe path.")
            z.extract(member, root)
            if i % 25 == 0:
                progress(10 + 75 * i / len(members), "Copying MINTRO…")
    if not EXE.exists():
        raise RuntimeError("MINTRO.exe is missing from the installer.")
    progress(88, "Adding shortcuts…")
    _shortcuts(remove=False)
    progress(94, "Registering with Windows…")
    _register(sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file()) // 1024)
    progress(100, "Installed")
    return EXE


def uninstall(quiet: bool = False) -> None:
    """Remove the program, shortcuts and Apps entry. Settings and wallets stay in %LOCALAPPDATA%\\MINTRO."""
    close_running(skip_self=True)
    _shortcuts(remove=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if not quiet:
        excluded = (store.load("defender.json") or {}).get("excluded")
        _message(f"MINTRO has been removed.\n\nYour settings and any wallets MINTRO made are kept in:\n{store.ROOT}"
                 "\n\nBack up wallet seed words before deleting that folder."
                 + (f"\n\nWindows Security still skips {excluded}. To undo that: Windows Security > Virus & threat "
                    "protection > Manage settings > Exclusions." if excluded else ""), "MINTRO")
    # This process runs from APP_DIR, so the folder goes once it has exited. ping, not timeout: timeout needs a
    # console and quits at once in a detached process. Retries cover a slow exit.
    remove = f'for /l %i in (1,1,30) do @(if exist "{APP_DIR}" (ping -n 2 127.0.0.1 >nul & rmdir /s /q "{APP_DIR}" 2>nul))'
    subprocess.Popen(f'cmd /s /c "{remove}"', creationflags=NO_WINDOW | DETACHED, close_fds=True)


def close_running(skip_self: bool = False, handoff: bool = False) -> None:
    """Ask a running MINTRO to close, then force it if needed.

    handoff=True asks it to leave its miners mining for the version about to be installed (it adopts them on
    start); otherwise closing stops the miners as usual.
    """
    if not (handoff and _ask_handoff()):
        for hwnd in _card_windows():
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    for _ in range(16):
        if not _running(skip_self):
            return
        time.sleep(0.5)
    me = os.getpid()
    for pid in _running(skip_self):
        if pid != me:  # /T would take the handed-over miners down with it
            tree = [] if handoff else ["/T"]
            subprocess.run(["taskkill", "/F", *tree, "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)


def _ask_handoff(port: int = 8777) -> bool:
    import json
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/handoff", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.loads(r.read()).get("ok"))
    except Exception:
        return False


def set_version(version: str) -> None:
    """After a self-update: show the new version in Settings > Apps."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
    except OSError:
        pass


def _card_windows() -> list[int]:
    """MINTRO card windows (titled MINTRO, WinForms class). Kept here so the installer needn't bundle the app."""
    import ctypes.wintypes as wt
    user32, found = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        title, cls = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, title, 64)
        if title.value == "MINTRO":
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value.startswith("WindowsForms"):
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def _running(skip_self: bool) -> list[int]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MINTRO.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    pids = [int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"MINTRO.exe"')]
    return [p for p in pids if not (skip_self and p == os.getpid())]


def _shortcuts(remove: bool) -> None:
    env = {**os.environ, "MINTRO_EXE": str(EXE), "MINTRO_DIR": str(APP_DIR), "MINTRO_REMOVE": "1" if remove else ""}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SHORTCUTS],
                   env=env, capture_output=True, timeout=60, creationflags=NO_WINDOW, check=not remove)


def _register(size_kb: int) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in {"DisplayName": "MINTRO", "DisplayVersion": __version__, "Publisher": "MINTRO",
                            "DisplayIcon": f"{EXE},0", "InstallLocation": str(APP_DIR),
                            "UninstallString": f'"{EXE}" --uninstall'}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in {"NoModify": 1, "NoRepair": 1, "EstimatedSize": int(size_kb)}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def _remove_tree(path: Path) -> None:
    for attempt in range(6):
        if not path.exists():
            return
        shutil.rmtree(path, ignore_errors=attempt < 5)
        time.sleep(0.5)


def _message(text: str, title: str, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)
