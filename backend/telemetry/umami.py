"""Sending events to the maintainer's Umami (`/api/send`). Fire and forget: a send never raises,
and nothing is sent when the owner has not chosen, JN_TELEMETRY=off, or no website id is set."""
import logging
from datetime import datetime, timezone

import httpx

from backend.telemetry import level as L

logger = logging.getLogger("jobnavigator.telemetry")

UMAMI_HOST = "https://a.viktoresadze.com"
UMAMI_WEBSITE_ID = ""   # Umami › Settings › Websites › JobNavigator app; empty = nothing is sent
HOSTNAME = "jobnavigator"   # never the install's own domain
TIMEOUT = 10.0
_transport = None           # tests put an httpx.MockTransport here


def _user_agent() -> str:
    from backend.version import APP_VERSION
    # browser-like, so Umami's bot filter keeps server events (job-ops does the same)
    return ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/130.0 Safari/537.36 JobNavigator/{APP_VERSION}")


def body(name: str, data: dict) -> dict:
    return {"type": "event", "payload": {"website": UMAMI_WEBSITE_ID, "hostname": HOSTNAME,
                                         "url": "/server", "name": name, "data": data, "language": "en"}}


async def send(events) -> int:
    """POST each (name, data); returns how many Umami accepted."""
    if not UMAMI_WEBSITE_ID or not events:
        return 0
    sent = 0
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=_transport,
                                     headers={"User-Agent": _user_agent()}) as client:
            for name, data in events:
                resp = await client.post(f"{UMAMI_HOST}/api/send", json=body(name, data))
                if resp.status_code < 300:
                    sent += 1
    except Exception as e:   # Umami down, no network: the app carries on
        logger.warning(f"Telemetry not sent: {type(e).__name__}")
    return sent


def _session():
    from backend.models.db import SessionLocal
    return SessionLocal()


async def send_start() -> int:
    """At startup: `app_started` (and `install_first_start` the first time)."""
    from backend.accounts.context import unscoped
    from backend.accounts.settings import get_install_setting
    from backend.telemetry.events import heartbeat
    with unscoped():
        db = _session()
        try:
            level = L.effective_level(db)
            if not L.sends_anything(level) or not UMAMI_WEBSITE_ID:
                return 0
            first = not get_install_setting(db, L.INSTALL_ID_KEY)
            events = [("app_started", heartbeat(db, "app_started"))]
            if first:
                events.insert(0, ("install_first_start", {"install_id": events[0][1]["install_id"],
                                                          "version": events[0][1]["version"]}))
            db.commit()   # no transaction waits on the network
        finally:
            db.close()
    return await send(events)


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
