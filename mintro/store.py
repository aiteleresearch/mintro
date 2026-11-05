"""Small JSON files under data/: settings, market cache, benchmark result."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

# Installed (frozen) app: user data lives in %LOCALAPPDATA%\MINTRO, apart from the program files.
# From source: next to the code, as before.
if getattr(sys, "frozen", False):
    ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MINTRO"
else:
    ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MINERS = ROOT / "miners"

_lock = threading.Lock()


def load(name: str, default=None):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(name: str, obj) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = DATA / (name + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, DATA / name)
                return
            except PermissionError:  # Windows: a reader (or antivirus scan) briefly holds the file
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
