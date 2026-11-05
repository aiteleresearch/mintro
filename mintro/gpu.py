"""Discrete graphics cards: which one this PC has and a first guess at its mining speed (the GPU lane).

The guess is replaced by the measured speed after a few minutes of mining.
"""
from __future__ import annotations

import re

# ProgPoW-family (FiroPow, MeowPow, KawPow) speeds of common cards in MH/s, desktop versions
_MHS = [("5090", 80), ("5080", 55), ("5070", 36), ("5060", 24), ("4090", 60), ("4080", 45), ("4070 ti", 35),
        ("4070", 30), ("4060 ti", 22), ("4060", 18), ("3090", 48), ("3080", 45), ("3070", 30), ("3060 ti", 30),
        ("3060", 22), ("3050", 13), ("2080", 32), ("2070", 26), ("2060", 18), ("1660", 14), ("1080", 22),
        ("1070", 17), ("7900", 55), ("7800", 38), ("7700", 30), ("7600", 20), ("6950", 40), ("6900", 38),
        ("6800", 35), ("6700", 26), ("6600", 15), ("a770", 20), ("a750", 18)]
DISCRETE = re.compile(r"geforce|rtx|gtx|quadro|radeon rx|radeon pro|arc a\d|arc b\d", re.I)


def discrete(hw: dict) -> dict | None:
    """{name, hps, watts} for the first discrete GPU, or None (integrated graphics can't mine usefully)."""
    name = next((g for g in hw.get("gpus") or [] if DISCRETE.search(g)), None)
    if not name:
        return None
    low = name.lower()
    mhs = next((m for key, m in _MHS if key in low), 15)
    laptop = hw.get("laptop") or "laptop" in low
    if laptop:
        mhs *= 0.6  # laptop GPUs run at much lower power limits
    return {"name": name, "hps": mhs * 1e6, "watts": 110 if laptop else 180}
