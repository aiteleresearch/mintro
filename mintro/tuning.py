"""Auto-tuning: size mining to this PC, its free memory, and whether someone is using it right now."""
from __future__ import annotations

import ctypes
import math
import os

LOW_RAM_GB = 2.6     # RandomX "fast" mode keeps a ~2.3 GB dataset in RAM; below this it would swap
LIGHT_FACTOR = 0.15  # RandomX "light" mode (256 MB) hashes at roughly this fraction of fast mode
ACTIVE_S = 90        # keyboard or mouse input this recently means the PC is in use

# Windows process priority classes
PRIORITY = {"idle": 0x40, "below_normal": 0x4000, "normal": 0x20}


def tier(hw: dict) -> str:
    """A plain-words class for this machine, e.g. "Standard laptop"."""
    score = (hw["cores"] + 0.25 * (hw["threads"] - hw["cores"])) * hw["allcore_ghz"] * hw["arch"]
    ram = hw.get("ram_gb") or 8
    name = "Light" if score < 12 or ram < 6 else "Performance" if score >= 35 and ram >= 16 else "Standard"
    return f"{name} {'laptop' if hw.get('laptop') else 'desktop'}"


def memory_mode(hw: dict) -> str:
    free = hw.get("free_gb") or 0
    return "light" if 0 < free < LOW_RAM_GB else "fast"


def settings(mode: str, hw: dict, active: bool) -> dict:
    """XMRig thread hint and priorities for a power mode.

    XMRig already limits RandomX to one thread per 2 MB of L3 cache (hw["rx_threads"]); its thread hint is
    a percentage of *all* logical CPUs, so the wanted thread count is converted into that percentage.
    """
    base, logical = hw.get("rx_threads") or 1, hw.get("threads") or 1
    thin = hw.get("laptop") and hw.get("cpu_watts", 18) <= 18  # 15 W-class ultrabook chips heat up fast
    if mode == "eco":
        want, cls = base * 0.5, "idle"
    elif mode == "balanced":
        want, cls = base, "below_normal"
    elif mode == "max":
        want, cls = logical, "normal"
    else:  # auto: back off while the PC is in use; full speed when it's idle
        if active:
            want, cls = base * (0.5 if thin else 0.75), "idle"
        else:
            want, cls = base * (0.75 if thin else 1.0), "below_normal" if hw.get("laptop") else "normal"
    threads = max(1, min(logical, round(want)))
    # cpuminer-opt algorithms (yespower, yescrypt...) aren't cache-limited like RandomX: size them on all threads
    share = {"eco": 0.25, "balanced": 0.5, "max": 1.0}.get(mode) or (
        (0.25 if thin else 0.4) if active else (0.5 if thin else 0.75))
    return {"threads": threads, "hint": min(100, math.ceil(100 * threads / logical)),
            "cpu_threads": max(1, round(logical * share)), "priority_arg": 1, "priority_class": cls}


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input in this Windows session."""
    if os.name != "nt":
        return 1e9
    info = _LastInput(cbSize=ctypes.sizeof(_LastInput))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


def user_active() -> bool:
    return idle_seconds() < ACTIVE_S


def set_priority(proc, cls: str) -> bool:
    """Change a running miner's priority class without restarting it."""
    handle = getattr(proc, "_handle", None)
    if os.name != "nt" or handle is None:
        return False
    return bool(ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(int(handle)), PRIORITY[cls]))
