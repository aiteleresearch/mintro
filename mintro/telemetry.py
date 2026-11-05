"""Anonymous heartbeat for the public miner counter on the MINTRO website (config.STATS_URL).

Every 10 minutes, and whenever mining starts or stops, MINTRO sends exactly this:
    {"id": <random install ID made on first run>, "v": <app version>, "mining": true/false, "lanes": ["cpu"]}
No wallet address, no name, no hardware details. The service keeps the ID and when it was last seen, and
throws away IP addresses after using a scrambled form of them to stop one machine inflating the count.
People turn it off under Settings ("Count me in the public miner counter"). The service's code is in
server/stats; the method is in docs/STATS.md.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.request

from . import __version__, config, market, store

log = logging.getLogger("mintro.telemetry")

PING_EVERY_S = 600


def install_id() -> str:
    """Random, made once per install; kept in the data folder so updates keep counting the same PC once."""
    saved = store.load("install.json") or {}
    if not saved.get("id"):
        saved = {"id": secrets.token_hex(16), "created": time.time()}
        store.save("install.json", saved)
    return saved["id"]


def enabled() -> bool:
    return bool(config.STATS_URL) and (store.load("app-prefs.json") or {}).get("share_stats", True) is not False


class Heartbeat:
    def __init__(self):
        self._last_at, self._last_mining = 0.0, None

    def tick(self, mining: bool, lanes: list[str]) -> None:
        """Call often; it only sends every PING_EVERY_S, or straight away when mining starts or stops."""
        if not enabled():
            return
        now = time.time()
        if mining == self._last_mining and now - self._last_at < PING_EVERY_S:
            return
        self._last_at, self._last_mining = now, mining
        body = json.dumps({"id": install_id(), "v": __version__, "mining": mining, "lanes": lanes}).encode()
        req = urllib.request.Request(config.STATS_URL.rstrip("/") + "/v1/ping", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": market.USER_AGENT})
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:
            log.info("stats heartbeat not sent: %s", e)
