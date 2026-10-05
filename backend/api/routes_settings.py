"""GET /settings and PATCH /settings endpoints, plus the MT-9 section table and policies."""
import json
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.models.db import get_db, Account, SectionPolicy
from backend.scheduler import configure_scheduler
from backend.analyzer.cv_scorer import reset_scoring_semaphore
from backend.scraper._shared.dedup import reload_tracking_params
from backend.accounts import settings as acct_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


_REDACT_SUFFIXES = ("_password", "_api_key", "_session_id", "_secret")
_REDACT_KEYS = {"dashboard_api_key", "gmail_refresh_token"}
# Server-side only, never listed (not even redacted) and not writable (not a known key).
_HIDDEN_KEYS = {"account_cookie_secret"}


def _is_secret(key: str) -> bool:
    return key in _REDACT_KEYS or any(key.endswith(s) for s in _REDACT_SUFFIXES)


@router.get("")
def get_settings(meta: bool = Query(False, description="Add `_meta` (per-key section, source, editable); always on for members"),
                 db: Session = Depends(get_db)):
    """Return the settings the current account sees as a key-value map. Sensitive values are redacted. For the owner these are the install values (the response is unchanged unless `?meta=1`); a member gets inherited install values plus its own rows, and a `_meta` key with `{key: {section, source, editable}}`."""
    rows = [r for r in acct_settings.effective_rows(db) if r[0] not in _HIDDEN_KEYS]
    result = {}
    for key, value, _source in rows:
        # Redact secrets — return empty string if not set, "••••••" if set
        if _is_secret(key):
            result[key] = "" if not value else "•" * 6
            continue
        try:
            result[key] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            result[key] = value
    if meta or not acct_settings.is_owner_caller(db):
        info = acct_settings.key_meta(db, [k for k, _v, _s in rows])
        for key, _value, source in rows:
            info[key]["source"] = source
        result["_meta"] = info
    return result


@router.get("/sections")
def get_sections(db: Session = Depends(get_db)):
    """The settings sections: id (matches the Settings screen anchors where `ui` lists them), label, scope ('policy' | 'own_always' | 'owner_only'), default mode for 'policy' sections ('inherit' | 'own'), and the keys each holds. For a member each section also carries `mode`: that member's effective mode ('inherit' | 'own' | 'own_always' | 'owner_only')."""
    out = acct_settings.sections_payload()
    member = acct_settings.member_account(db)
    if member is not None:
        for sec in out:
            sec["mode"] = acct_settings.section_mode(db, member, sec["id"])
    return out


@router.patch("")
def update_settings(updates: dict, db: Session = Depends(get_db)):
    """Update one or more settings; only keys the app reads are writable (unknown -> 400 as a group), and values are validated (integers non-negative, `*_cron` a parseable 5-field expression, enums known) since a bad one could crash configure_scheduler() and prevent the backend from starting. The owner writes install values; a member writes its own values, and only in sections it owns (else 403, nothing written)."""
    from backend.seed import invalid_setting_values, unknown_setting_keys

    unknown = unknown_setting_keys(updates.keys())
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown setting: {', '.join(sorted(unknown))}",
        )

    # The redacted placeholder is never a real value — it is skipped below too.
    checkable = {k: v for k, v in updates.items()
                 if not (isinstance(v, str) and v == "•" * 6)}
    problems = invalid_setting_values(checkable)
    if problems:
        raise HTTPException(
            status_code=400,
            detail="Invalid setting value — " + "; ".join(problems),
        )

    try:
        targets = acct_settings.write_targets(db, checkable.keys())
    except acct_settings.SettingNotWritable as e:
        raise HTTPException(
            status_code=403,
            detail="These settings are managed by the account owner: " + ", ".join(e.keys),
        )

    warnings: list[str] = []
    updated = []
    install_updated = []
    for key, value in updates.items():
        if isinstance(value, str) and value == "•" * 6:
            continue
        stored = json.dumps(value) if isinstance(value, (list, dict, bool)) else str(value)
        target = targets.get(key)
        acct_settings.put_setting(db, key, stored, account_id=target)
        updated.append(key)
        if target is None:
            install_updated.append(key)
    db.commit()

    if not install_updated:
        # A member's own values touch no process-wide state (scheduler timing, semaphores
        # and dedup params are read from install values).
        return {"updated": updated, "warnings": warnings}

    # A member writing install values through the owner unlock (MT-14): the reconfigure
    # steps below must read the install values, not that member's own.
    from contextlib import nullcontext
    from backend.accounts.context import unscoped
    member_caller = not acct_settings.is_owner_caller(db)

    def _reconfigure(name: str, fn) -> None:
        """Run one post-update reconfigure; a failure becomes a warning naming the step.

        The exception text stays in the server log: it can carry file paths, connection
        strings and stack detail, and the response is not the place for it.
        """
        try:
            with (unscoped() if member_caller else nullcontext()):
                fn()
        except Exception:
            warnings.append(f"{name} failed — see server logs")
            logger.exception("%s failed after settings update", name)

    timing_keys = {
        "scrape_interval_minutes", "email_check_interval_minutes",
        "backup_cron", "digest_cron", "h1b_cron", "cleanup_cron", "reject_cron",
    }
    if timing_keys & set(install_updated):
        _reconfigure("configure_scheduler", configure_scheduler)

    if "scoring_max_concurrent" in install_updated:
        _reconfigure("reset_scoring_semaphore", reset_scoring_semaphore)

    if "tailoring_max_concurrent" in install_updated:
        def _reset_tailoring():
            from backend.api.routes_resumes import reset_tailoring_semaphore
            reset_tailoring_semaphore()
        _reconfigure("reset_tailoring_semaphore", _reset_tailoring)

    if "dedup_tracking_params" in install_updated:
        _reconfigure("reload_tracking_params", reload_tracking_params)

    return {"updated": updated, "warnings": warnings}


def _require_owner(db):
    # MT-14: a member whose browser holds a live owner unlock acts as the owner here too.
    if not acct_settings.acts_as_owner(db):
        raise HTTPException(status_code=403, detail="Only the account owner can change section policies")


@router.get("/policies")
def get_policies(db: Session = Depends(get_db)):
    """Owner only: every member's effective mode per 'policy' section, `{account_id: {section: mode}}`."""
    _require_owner(db)
    from backend.accounts.context import unscoped
    with unscoped():
        members = db.query(Account.id).filter(Account.role != "owner").all()
    out = {}
    for (acc_id,) in members:
        out[str(acc_id)] = {
            sid: acct_settings.section_mode(db, acc_id, sid)
            for sid, sec in acct_settings.SETTING_SECTIONS.items()
            if sec["scope"] == acct_settings.POLICY
        }
    return out


@router.patch("/policies")
def update_policy(body: dict, db: Session = Depends(get_db)):
    """Owner only: set one member's mode for one 'policy' section. Body `{account_id, section, mode}` with mode 'inherit' | 'own'. A member's own values are kept when a section goes back to inherit (they apply again if it is flipped to own)."""
    _require_owner(db)
    body = body or {}
    section = body.get("section")
    mode = body.get("mode")
    sec = acct_settings.SETTING_SECTIONS.get(section) if isinstance(section, str) else None
    if sec is None:
        raise HTTPException(status_code=400, detail=f"Unknown section: {section!r}")
    if sec["scope"] != acct_settings.POLICY:
        raise HTTPException(status_code=400, detail=f"Section {section!r} is {sec['scope']}; it has no policy")
    if mode not in acct_settings.POLICY_MODES:
        raise HTTPException(status_code=400, detail="mode must be 'inherit' or 'own'")
    try:
        acc_id = uuid.UUID(str(body.get("account_id")))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="account_id must be an account id")
    account = db.query(Account).filter(Account.id == acc_id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.role == "owner":
        raise HTTPException(status_code=400, detail="The owner's values are the install values; policies apply to members")
    row = (db.query(SectionPolicy)
           .filter(SectionPolicy.account_id == acc_id, SectionPolicy.section == section).first())
    if row is None:
        db.add(SectionPolicy(account_id=acc_id, section=section, mode=mode))
    else:
        row.mode = mode
    db.commit()
    return {"account_id": str(acc_id), "section": section, "mode": mode}


@router.get("/defaults")
def get_defaults():
    """Seeded defaults, so an editor can offer "Reset to default" without hardcoding a second copy of every prompt in the frontend."""
    from backend.seed import DEFAULT_SETTINGS
    return {k: v[0] for k, v in DEFAULT_SETTINGS.items()}
