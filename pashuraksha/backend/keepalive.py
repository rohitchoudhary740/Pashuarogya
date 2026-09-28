"""Keep the free-tier deployment awake.

A free Render instance is spun down after ~15 minutes with no inbound HTTP
traffic, and the next visitor then waits ~50 seconds for a cold start. Mid-demo
that is fatal.

Two independent guards, because they fail in different ways:

  1. This module — the instance pings its own public URL on a timer. Its own
     request arrives back through Render's router as ordinary inbound traffic,
     so the idle clock never reaches 15 minutes. Cheap and needs no third party.

  2. .github/workflows/keepalive.yml — an external cron that pings from GitHub.
     This is the one that matters after a deploy, a crash or an OOM kill: once
     the instance IS down, the thread below is down with it and cannot wake
     anything. Only an outside request can.

Neither runs locally: without PASHU_PUBLIC_URL or RENDER_EXTERNAL_URL there is
nothing to ping, and the thread exits immediately.
"""
import os
import random
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

# Render injects RENDER_EXTERNAL_URL; PASHU_PUBLIC_URL overrides it anywhere else.
PUBLIC_URL = (os.environ.get("PASHU_PUBLIC_URL")
              or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
# 10 minutes: comfortably inside Render's ~15-minute idle window, and only
# ~144 requests a day against a health check that touches no table.
INTERVAL = int(os.environ.get("PASHU_KEEPALIVE_SECONDS", "600"))
STATE = {"enabled": False, "url": None, "last_ok": None, "last_error": None,
         "pings": 0, "failures": 0}


def _ping_once(url: str):
    req = urllib.request.Request(
        url, headers={"User-Agent": "PashuAarogya-keepalive/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status


def _loop():
    url = PUBLIC_URL + "/healthz"
    while True:
        # jitter, so the self-ping and the GitHub cron never line up into one
        # burst followed by a long silence
        time.sleep(max(60, INTERVAL) + random.randint(-45, 45))
        try:
            code = _ping_once(url)
            STATE["pings"] += 1
            if 200 <= code < 400:
                STATE["last_ok"] = datetime.utcnow().isoformat()
                STATE["last_error"] = None
            else:
                STATE["failures"] += 1
                STATE["last_error"] = f"HTTP {code}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            # A failed ping is not worth crashing over: the next tick retries,
            # and the external cron is the real safety net.
            STATE["failures"] += 1
            STATE["last_error"] = f"{type(e).__name__}: {e}"[:200]


def start():
    """Begin pinging, if a public URL is known. Returns True when started."""
    if not PUBLIC_URL:
        return False
    STATE.update({"enabled": True, "url": PUBLIC_URL + "/healthz"})
    threading.Thread(target=_loop, daemon=True).start()
    print(f"[keepalive] self-ping every ~{INTERVAL}s -> {STATE['url']}", flush=True)
    return True
