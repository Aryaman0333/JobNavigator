"""Gmail connect per account (MT-19). Rules and storage: backend/email_monitor/gmail_auth.py.

- GET  /gmail/status      {status: connected | none | expired, source: account | env | null,
                          configured: client id/secret present in .env}
- GET  /gmail/connect     {url}: Google's consent URL (gmail.readonly, offline, prompt=consent)
                          with a signed single-use `state` bound to the caller's account
                          (10 min). 503 `gmail_not_configured` without the .env client.
- GET  /gmail/callback    public (Google redirects the browser here): checks the state,
                          exchanges the code, stores the refresh token on the state's account,
                          then 303 → /settings?gmail=connected#gmail, or
                          /settings?gmail=error&reason=<code>#gmail.
- POST /gmail/disconnect  clears the caller's stored token (the owner's .env token, if any,
                          stays in use: it can only be removed from .env).

The redirect URI is `<browser origin>/api/gmail/callback`; the owner adds it once as an
authorised redirect URI of the OAuth client in the Google Cloud console.
"""
import logging
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.accounts.context import current_account, unscoped
from backend.accounts.settings import _account_row, install_row, member_account
from backend.email_monitor import gmail_auth
from backend.models.db import Account, get_db, get_owner_id

logger = logging.getLogger("jobnavigator.gmail")

router = APIRouter(prefix="/gmail", tags=["gmail"])

TOKEN_URL = "https://oauth2.googleapis.com/token"


def _caller_id(db) -> uuid.UUID:
    acc = current_account.get()
    if acc is not None:
        return acc
    owner = get_owner_id(db)
    if owner is None:
        raise HTTPException(status_code=409, detail="no_account")
    return owner


def _back(ok: bool, reason: str = "") -> RedirectResponse:
    q = {"gmail": "connected"} if ok else {"gmail": "error", "reason": reason}
    return RedirectResponse(f"/settings?{urlencode(q)}#gmail", status_code=303)


@router.get("/status", summary="Gmail connection of the current account")
def gmail_status(db: Session = Depends(get_db)):
    return gmail_auth.status(db)


@router.get("/connect", summary="Google consent URL for the current account")
def gmail_connect(request: Request, db: Session = Depends(get_db)):
    client_id, _secret = gmail_auth.client_config()
    if not gmail_auth.is_configured():
        raise HTTPException(status_code=503, detail="gmail_not_configured")
    redirect_uri = gmail_auth.redirect_uri(request)
    state = gmail_auth.make_state(db, _caller_id(db), redirect_uri)
    return {"url": gmail_auth.consent_url(client_id, redirect_uri, state), "redirect_uri": redirect_uri}


@router.get("/callback", summary="Google OAuth redirect target (public)", include_in_schema=False)
async def gmail_callback(code: str = None, state: str = None, error: str = None,
                         db: Session = Depends(get_db)):
    try:
        payload = gmail_auth.read_state(db, state)
    except gmail_auth.StateError as e:
        logger.warning("Gmail connect refused: %s", e.reason)
        return _back(False, e.reason)
    if error:
        logger.info("Gmail connect: Google returned %s", error)
        return _back(False, error[:40])
    if not code:
        return _back(False, "no_code")
    try:
        account_id = uuid.UUID(payload["a"])
    except ValueError:
        return _back(False, "invalid_state")
    with unscoped():
        acc = db.query(Account.id, Account.role).filter(Account.id == account_id).first()
    if acc is None:
        return _back(False, "account_gone")

    client_id, client_secret = gmail_auth.client_config()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(TOKEN_URL, data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": payload["r"],
                "grant_type": "authorization_code",
            })
    except Exception as e:
        logger.error("Gmail code exchange failed: %s", e)
        return _back(False, "exchange_failed")
    if resp.status_code != 200:
        logger.error("Gmail code exchange failed (%s): %s", resp.status_code, resp.text[:300])
        return _back(False, "exchange_failed")
    refresh = (resp.json() or {}).get("refresh_token") or ""
    if not refresh:
        return _back(False, "no_refresh_token")

    target = None if acc.role == "owner" else acc.id
    with unscoped():
        gmail_auth.store_token(db, target, refresh)
    logger.info("Gmail connected for account %s", acc.id)
    return _back(True)


@router.post("/disconnect", summary="Forget the current account's Gmail token")
def gmail_disconnect(db: Session = Depends(get_db)):
    target = member_account(db)
    row = install_row(db, gmail_auth.TOKEN_KEY) if target is None else _account_row(db, target, gmail_auth.TOKEN_KEY)
    if row is not None and row.value:
        row.value = ""
    gmail_auth.clear_status(db, target, commit=False)
    db.commit()
    return gmail_auth.status(db)
