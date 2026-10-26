"""Sending events to the maintainer's Umami (`/api/send`). Fire and forget: a send never raises,
and nothing is sent when the owner has not chosen, JN_TELEMETRY=off, or no website id is set."""
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from backend.telemetry import level as L

logger = logging.getLogger("jobnavigator.telemetry")

UMAMI_HOST = "https://a.viktoresadze.com"
UMAMI_WEBSITE_ID = ""   # Umami › Settings › Websites › JobNavigator app; empty = nothing is sent
HOSTNAME = "jobnavigator.local"   # never the install's own domain (Umami wants a dotted name)
TIMEOUT = 10.0
_transport = None           # tests put an httpx.MockTransport here


def _user_agent() -> str:
    from backend.version import APP_VERSION
    # browser-like, so Umami's bot filter keeps server events (job-ops does the same)
    return ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/130.0 Safari/537.36 JobNavigator/{APP_VERSION}")


PAGE_VIEW = "page_view"   # sent to Umami as a page view (no event name), not as an event


def body(name: str, data: dict, url: str = "/server") -> dict:
    payload = {"website": UMAMI_WEBSITE_ID, "hostname": HOSTNAME, "url": url, "language": "en"}
    if name != PAGE_VIEW:
        payload.update(name=name, data=data)
    return {"type": "event", "payload": payload}


async def send(events, url: str = "/server") -> int:
    """POST each (name, data); returns how many Umami accepted."""
    if not UMAMI_WEBSITE_ID or not events:
        return 0
    sent = 0
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=_transport,
                                     headers={"User-Agent": _user_agent()}) as client:
            for name, data in events:
                resp = await client.post(f"{UMAMI_HOST}/api/send", json=body(name, data, url))
                if resp.status_code < 300:
                    sent += 1
    except Exception as e:   # Umami down, no network: the app carries on
        logger.warning(f"Telemetry not sent: {type(e).__name__}")
    return sent


def _session():
    from backend.models.db import SessionLocal
    return SessionLocal()


async def send_start() -> int:
    """At startup: `app_started`. Never raises (it runs as a bare task in the app's lifespan)."""
    from backend.accounts.context import unscoped
    from backend.telemetry.events import heartbeat
    try:
        with unscoped():
            db = _session()
            try:
                level = L.effective_level(db)
                if not L.sends_anything(level) or not UMAMI_WEBSITE_ID:
                    return 0
                events = [("app_started", heartbeat(db, "app_started"))]
                db.commit()   # no transaction waits on the network
            finally:
                db.close()
        return await send(events)
    except Exception as e:
        logger.warning(f"Telemetry start event not sent: {type(e).__name__}")
        return 0


# ── browser events, relayed (the browser never talks to Umami) ──────────────
# The browser posts to this install's /api/telemetry/event; checked again here and sent with
# the server's agent, so Umami sees neither the user's browser and IP nor this install's address.



_NAME = re.compile(r"^[a-z_]{1,40}$")
_VALUE = re.compile(r"^[A-Za-z0-9_:.-]{1,32}$")
_PATH = re.compile(r"^/[a-z0-9:/_-]{0,80}$")
RELAY_PER_MINUTE = 120
_relayed: list = []


def clean_browser_event(name, data, url):
    """(name, data, url) when the event is well formed, else None. Values must be short ids,
    numbers or booleans; the path only lower-case words and ':id'."""
    if not isinstance(name, str) or not _NAME.match(name):
        return None
    if not isinstance(url, str) or not _PATH.match(url):
        url = "/"
    out = {}
    for k, v in (data or {}).items() if isinstance(data, dict) else ():
        if not isinstance(k, str) or not _NAME.match(k) or len(out) >= 8:
            continue
        if isinstance(v, bool) or isinstance(v, int):
            out[k] = v
        elif isinstance(v, str) and _VALUE.match(v):
            out[k] = v
    return name, out, url


async def relay(name, data, url) -> bool:
    """One browser event, when the install is at `full`. Never raises."""
    from backend.accounts.context import unscoped
    ev = clean_browser_event(name, data, url)
    if ev is None or not UMAMI_WEBSITE_ID:
        return False
    now = time.monotonic()
    _relayed[:] = [t for t in _relayed if now - t < 60]
    if len(_relayed) >= RELAY_PER_MINUTE:
        return False
    try:
        with unscoped():
            db = _session()
            try:
                if L.effective_level(db) != L.FULL:
                    return False
                iid = L.install_id(db)
            finally:
                db.close()
    except Exception:
        return False
    _relayed.append(now)
    name, data, url = ev
    return await send([(name, {**data, "install_id": iid})], url=url) == 1


async def send_daily() -> int:
    """The daily heartbeat and health events; stamps telemetry_last_sent_at when any got through."""
    from backend.accounts.context import unscoped
    from backend.accounts.settings import put_setting
    from backend.telemetry.events import daily_events
    with unscoped():
        db = _session()
        try:
            level = L.effective_level(db)
            if not L.sends_anything(level) or not UMAMI_WEBSITE_ID:
                return 0
            events = daily_events(db, level)
            db.commit()
        finally:
            db.close()
    sent = await send(events)
    if sent:
        with unscoped():
            db = _session()
            try:
                put_setting(db, L.LAST_SENT_KEY, datetime.now(timezone.utc).isoformat())
                db.commit()
            finally:
                db.close()
    return sent
