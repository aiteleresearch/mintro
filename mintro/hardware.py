"""What can this computer mine with? One PowerShell/CIM query on Windows, best effort elsewhere."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_PS_PROFILE = r"""
$c  = Get-CimInstance Win32_Processor | Select-Object -First 1
$os = Get-CimInstance Win32_OperatingSystem
$bs = $null
try { $bs = Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus -ErrorAction Stop | Select-Object -First 1 } catch {}
$r  = [System.Globalization.RegionInfo]::CurrentRegion
[pscustomobject]@{
  cpu      = $c.Name.Trim()
  cores    = [int]$c.NumberOfCores
  threads  = [int]$c.NumberOfLogicalProcessors
  l3_mb    = [math]::Round($c.L3CacheSize / 1024, 1)
  base_mhz = [int]$c.MaxClockSpeed
  ram_gb   = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
  free_gb  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
  gpus     = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
  laptop   = @(Get-CimInstance Win32_Battery).Count -gt 0
  on_ac    = if ($bs) { [bool]$bs.PowerOnline } else { $true }
  region   = $r.TwoLetterISORegionName
  currency = $r.ISOCurrencySymbol
} | ConvertTo-Json -Compress
"""

_PS_BATTERY = r"""
$b = Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus -ErrorAction Stop | Select-Object -First 1
'{0} {1}' -f [int]$b.Discharging, [int]$b.DischargeRate
"""


def _powershell(script: str, timeout: float = 30) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
    )
    return out.stdout.strip()


def detect() -> dict:
    hw = None
    if os.name == "nt":
        try:
            hw = json.loads(_powershell(_PS_PROFILE))
        except (OSError, ValueError, subprocess.SubprocessError):
            hw = None
    if hw:
        hw["source"] = "cim"
    else:
        hw = {**_detect_generic(), "source": "generic"}
    hw["gpus"] = [g for g in (hw.get("gpus") or []) if g]
    hw.update(classify(hw))
    return hw


def battery_watts() -> float | None:
    """Whole-system power draw in watts. Windows only reports it while running on battery."""
    if os.name != "nt":
        return None
    try:
        discharging, mw = _powershell(_PS_BATTERY, timeout=10).split()
        mw = int(mw)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return mw / 1000 if discharging == "1" and mw > 0 else None


def classify(hw: dict) -> dict:
    """Derived traits that the speed and power estimates are built on."""
    name = (hw.get("cpu") or "").lower()
    cores = max(1, int(hw.get("cores") or 1))
    threads = max(cores, int(hw.get("threads") or cores))
    laptop = bool(hw.get("laptop"))
    base = (hw.get("base_mhz") or 2500) / 1000
    allcore = min(base * 1.4, base + 1.2, 4.2) if laptop else min(base * 1.15, 5.2)
    l3 = float(hw.get("l3_mb") or 0)
    # XMRig runs one RandomX thread per 2 MB of L3 cache; more threads only fight over the cache
    rx_threads = max(1, min(threads, int(l3 // 2))) if l3 else max(1, cores // 2)
    rx_cores = min(rx_threads, cores)
    return {
        "cores": cores,
        "threads": threads,
        "arch": _arch_factor(name),
        "allcore_ghz": round(allcore, 2),
        "rx_threads": rx_threads,
        "rx_cores": rx_cores,
        "rx_ghz": round(allcore * (1 + 0.1 * (1 - rx_cores / cores)), 2),  # fewer busy cores boost higher
        "cpu_watts": _cpu_watts(name, laptop),
        "base_watts": 7 if laptop else 35,
        "gpu_kind": _gpu_kind(hw.get("gpus") or []),
    }


def _arch_factor(name: str) -> float:
    """Per-core, per-GHz mining speed of the CPU generation (rough, relative)."""
    if "ryzen" in name:
        if re.search(r"ryzen\s+ai\b", name):
            return 1.05
        m = re.search(r"ryzen\s+\d\s+(?:pro\s+)?(\d)\d{3}", name)
        series = {1: .65, 2: .7, 3: .8, 4: .8, 5: .85, 6: .95, 7: .95, 8: 1.0, 9: 1.05}
        return series.get(int(m.group(1)), .85) if m else .85
    if "epyc" in name or "threadripper" in name:
        return .9
    if "intel" in name:
        if "ultra" in name:
            return .85
        if re.search(r"celeron|pentium|atom|\bn\d{3}\b", name):
            return .45
        m = re.search(r"i[3579]-(\d{4,5})", name)
        if not m:
            return .6
        digits = m.group(1)
        gen = int(digits[:2]) if len(digits) == 5 or digits.startswith("1") else int(digits[0])
        return .5 if gen <= 5 else .6 if gen <= 7 else .65 if gen <= 10 else .75 if gen == 11 else .8
    return .6


def _cpu_watts(name: str, laptop: bool) -> int:
    """Typical sustained CPU power under full mining load, from the model suffix (U, H, HX, X, K...)."""
    m = re.search(r"\b\d{3,5}([a-z]{1,2})\d?\b", name)
    suffix = m.group(1) if m else ""
    if laptop:
        if suffix == "hx" or re.search(r"\bhx\b", name):
            return 55
        if suffix.startswith("h"):
            return 40
        if suffix == "p" or "ryzen ai" in name:
            return 28
        return 18
    return 120 if suffix in ("x", "k", "kf", "ks") else 88


def _gpu_kind(gpus: list) -> str:
    names = " | ".join(gpus).lower()
    if re.search(r"geforce|rtx|gtx|quadro|radeon rx|radeon pro|arc a\d|arc b\d", names):
        return "discrete"
    return "integrated" if names else "none"


def _detect_generic() -> dict:
    threads = os.cpu_count() or 2
    hw = {
        "cpu": platform.processor() or platform.machine() or "Unknown CPU",
        "cores": max(1, threads // 2), "threads": threads, "l3_mb": 0.0, "base_mhz": 0,
        "ram_gb": 0.0, "free_gb": 0.0, "gpus": [], "laptop": False, "on_ac": True,
        "region": "", "currency": "USD",
    }
    cpuinfo = _read("/proc/cpuinfo")
    if m := re.search(r"model name\s*:\s*(.+)", cpuinfo):
        hw["cpu"] = m.group(1).strip()
    if m := re.search(r"cpu cores\s*:\s*(\d+)", cpuinfo):
        hw["cores"] = int(m.group(1))
    if m := re.search(r"(\d+)K", _read("/sys/devices/system/cpu/cpu0/cache/index3/size")):
        hw["l3_mb"] = int(m.group(1)) / 1024
    if m := re.search(r"(\d+)", _read("/sys/devices/system/cpu/cpu0/cpufreq/base_frequency")):
        hw["base_mhz"] = int(m.group(1)) // 1000
    meminfo = _read("/proc/meminfo")
    if m := re.search(r"MemTotal:\s*(\d+)", meminfo):
        hw["ram_gb"] = round(int(m.group(1)) / 2**20, 1)
    if m := re.search(r"MemAvailable:\s*(\d+)", meminfo):
        hw["free_gb"] = round(int(m.group(1)) / 2**20, 1)
    batteries = list(Path("/sys/class/power_supply").glob("BAT*"))
    if batteries:
        hw["laptop"] = True
        hw["on_ac"] = _read(str(batteries[0] / "status")).strip() != "Discharging"
    return hw


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""
