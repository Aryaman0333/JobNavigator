"""LinkedIn session (Voyager cookie) status and refresh; the login is gated behind
LinkedIn's email-PIN checkpoint, so a refresh parks in `awaiting_pin` until the code is posted back here."""
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from backend.job_monitor import launch_background, JobAlreadyRunningError
from backend.scraper.sources.linkedin_extension import _session_path

logger = logging.getLogger("jobnavigator.linkedin")

router = APIRouter(prefix="/linkedin", tags=["linkedin"])

# LinkedIn's li_at cookie runs about a year, but the practical session lifetime
# is far shorter; treat a jar older than this as due for a refresh.
_STALE_AFTER_DAYS = 21


class PinIn(BaseModel):
    pin: str


@router.get("/session")
def session_status():
    """Cookie-jar age plus the phase of any refresh currently running."""
    from backend import refresh_linkedin_session as rls

    path = _session_path()   # the caller's own cookie jar (MT-16)
    state = rls.state()
    exists = os.path.exists(path)
    age_days = None
    refreshed_at = None
    if exists:
        mtime = os.path.getmtime(path)
        refreshed_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        age_days = round((time.time() - mtime) / 86400, 1)

    if not exists:
        status, summary = "missing", "No session yet — refresh to sign in."
    elif age_days is not None and age_days >= _STALE_AFTER_DAYS:
        status, summary = "stale", f"Last refreshed {int(age_days)}d ago — likely expired."
    else:
        status, summary = "ok", f"Refreshed {int(age_days)}d ago."

    return {
        "exists": exists,
        "age_days": age_days,
        "refreshed_at": refreshed_at,
        "status": status,
        "summary": summary,
        "phase": state.get("phase", "idle"),
        "detail": state.get("detail", ""),
    }


@router.post("/session/refresh", status_code=202)
async def session_refresh():
    """Start the interactive login. Poll /session until phase leaves 'running'. Signs in and saves the caller's own session (MT-16)."""
    from backend import refresh_linkedin_session as rls

    state = rls.state()
    if state.get("phase") in ("running", "awaiting_pin"):
        return {"run_id": None, "status": state["phase"]}
    try:
        run_id = launch_background("linkedin_session_refresh", rls.run_refresh,
                                   trigger="manual", scope_key="linkedin")
    except JobAlreadyRunningError:
        return {"run_id": None, "status": "running"}
    return {"run_id": run_id, "status": "running"}


@router.post("/session/pin")
def session_pin(body: PinIn):
    """Hand the emailed PIN to the waiting login (it polls the account's PIN file)."""
    from backend import refresh_linkedin_session as rls

    digits = "".join(c for c in (body.pin or "") if c.isdigit())
    if not digits:
        return {"ok": False, "detail": "Enter the digits from LinkedIn's email."}
    with open(rls.pin_file(), "w") as f:
        f.write(digits)
    return {"ok": True}
