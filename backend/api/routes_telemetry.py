"""The telemetry choice the app shows: the level in effect, whether JN_TELEMETRY locks it, whether
the owner has been asked, and — only at `full` with a website id — where the browser sends its
events. The choice itself is the owner-only setting `telemetry_level` (PATCH /api/settings)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.models.db import get_db

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.get("")
def telemetry_state(db: Session = Depends(get_db)):
    from backend.accounts.settings import is_owner_caller
    from backend.telemetry import level as L
    from backend.telemetry import umami as U
    level = L.effective_level(db)
    browser = level == L.FULL and bool(U.UMAMI_WEBSITE_ID)
    return {
        "level": level,
        "locked": L.env_level() is not None,
        "asked": L.chosen_level(db) != L.UNSET,
        "owner": is_owner_caller(db),
        "umami": {"host": U.UMAMI_HOST, "website_id": U.UMAMI_WEBSITE_ID} if browser else None,
    }
