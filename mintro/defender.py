"""Windows Security (Microsoft Defender) and the miner.

Defender reports every crypto miner as a threat; it names XMRig "Trojan:Win64/HashvaultMiner" and similar.
"Allow" in Protection history often doesn't last: the file has already been removed, and MINTRO's next
download is a new detection. The reliable fix is an exclusion for MINTRO's miner folder only, which the person
approves through Windows' own admin prompt. MINTRO never changes Windows Security on its own.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time

from . import store

SEE_MASK_NOCLOSEPROCESS = 0x40
ERROR_CANCELLED = 1223


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HWND), ("lpVerb", wt.LPCWSTR),
                ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR),
                ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD),
                ("hIconOrMonitor", wt.HANDLE), ("hProcess", wt.HANDLE)]


def allow_miner_folder() -> str:
    """Ask Windows (admin prompt) to skip scanning MINTRO's miner folder. Returns "ok", "cancelled" or "failed"."""
    store.MINERS.mkdir(parents=True, exist_ok=True)
    folder = str(store.MINERS).replace("'", "''")
    script = f"try {{ Add-MpPreference -ExclusionPath '{folder}' -ErrorAction Stop; exit 0 }} catch {{ exit 2 }}"
    code = run("powershell.exe", f'-NoProfile -NonInteractive -WindowStyle Hidden -Command "{script}"', verb="runas")
    if code is None:
        return "cancelled"
    if code != 0:
        return "failed"
    store.save("defender.json", {"excluded": str(store.MINERS), "at": time.time()})
    return "ok"


def miner_folder_allowed() -> bool:
    """Whether the person approved the exclusion through MINTRO (Windows doesn't let non-admins read exclusions)."""
    return (store.load("defender.json") or {}).get("excluded") == str(store.MINERS)


def open_protection_history() -> None:
    os.startfile("windowsdefender://threat/")


def run(file: str, params: str, verb: str = "open", timeout_s: int = 180) -> int | None:
    """ShellExecuteEx and wait. Returns the exit code, or None if the person declined the admin prompt."""
    info = _ShellExecuteInfo(cbSize=ctypes.sizeof(_ShellExecuteInfo), fMask=SEE_MASK_NOCLOSEPROCESS,
                             lpVerb=verb, lpFile=file, lpParameters=params, nShow=0)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            return None
        raise OSError(error, "Windows couldn't run the command")
    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, timeout_s * 1000)
        code = wt.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
