"""Per-browser account sessions, PINs and account selection (MT-10).

Three layers, checked by the HTTP middleware in `backend.main` in this order:

1. Install password: `dashboard_api_key`, sent as the `X-API-Key` header or the
   `jn_session` cookie (unchanged since before multi-tenancy).
2. Account: which account the request acts for.
   * `X-Account: <account uuid>` header, honoured only together with the `X-API-Key`
     header (API clients, the extension). No PIN, per spec. Unknown id -> 401
     `{"detail": "invalid_account"}`.
   * else the signed `jn_account` cookie, issued by `POST /api/auth/switch`. Each
     browser holds its own; the server keeps no "current account".
   * else, with exactly one account, the owner (a single-user install never sees a picker).
   * else 401 `{"detail": "account_required"}` (plus header `X-JN-Auth: account`), which
     the UI turns into the account picker. A tampered, expired or stale cookie counts as
     no cookie.
3. PIN, checked by `POST /api/auth/switch` only (see `check_switch`).

Cookie `jn_account` = `<payload>.<sig>`, both base64url without padding:
  payload = JSON {"a": account id, "p": PIN fingerprint, "e": expiry (epoch s),
                  "u": owner unlock expiry (epoch s, 0 = locked)}
  sig     = HMAC-SHA256(server secret, payload)
The server secret is the install setting `account_cookie_secret` (generated on first use,
section 'system' = owner only, never returned by GET /api/settings, not writable through
PATCH). "p" is the first 16 hex chars of sha256(pin_hash) (empty without a PIN), so
setting, changing or removing an account's PIN invalidates every cookie issued for it.
"u" is set by `POST /api/auth/verify-owner-pin` (15 minutes); the middleware exposes it
as `request.state.owner_unlocked_until` for the owner-PIN unlock of MT-14.

PIN hashes: `scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>` (hashlib.scrypt, 16-byte random
salt per hash; no bcrypt/argon2 in requirements.txt).

Wrong PINs: 5 wrong tries for one target account -> that account is cooling down for
30 s (in-memory, per process; 429 with Retry-After). A wrong PIN against a PIN'd member
also counts against the owner when the owner has a PIN (the owner PIN covers member
PINs, so every such guess is also a guess of the owner PIN), and while the owner is
cooling down the owner PIN no longer covers member PINs.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
import weakref
from typing import Optional

COOKIE_NAME = "jn_account"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30          # same lifetime as jn_session
SECRET_KEY = "account_cookie_secret"
OWNER_UNLOCK_SECONDS = 15 * 60

PIN_MAX_FAILURES = 5
PIN_COOLDOWN_SECONDS = 30.0

ACCOUNT_REQUIRED = "account_required"
INVALID_ACCOUNT = "invalid_account"
AUTH_HEADER = "X-JN-Auth"                    # value "account" on an account_required 401

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def _now() -> float:
    return time.time()


def _mono() -> float:
    return time.monotonic()


# ── PIN hashing ──────────────────────────────────────────────────────────────

def valid_pin_format(pin) -> bool:
    return isinstance(pin, str) and len(pin) == 4 and pin.isascii() and pin.isdigit()


def hash_pin(pin: str) -> str:
    if not valid_pin_format(pin):
        raise ValueError("a PIN is exactly 4 digits")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_pin(pin, stored: Optional[str]) -> bool:
    if not stored or not valid_pin_format(pin):
        return False
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def pin_fingerprint(pin_hash: Optional[str]) -> str:
    return hashlib.sha256(pin_hash.encode()).hexdigest()[:16] if pin_hash else ""


# ── Accounts (plain rows, ≤5 per install) ────────────────────────────────────

def load_accounts(db) -> list:
    """Every account as a dict, owner first then by creation. Account is not
    AccountScoped, so this sees every account under any context."""
    from backend.models.db import Account
    rows = (db.query(Account.id, Account.name, Account.color, Account.role, Account.pin_hash,
                     Account.created_at)
            .all())
    out = [{"id": r.id, "name": r.name, "color": r.color, "role": r.role, "pin_hash": r.pin_hash,
            "created_at": r.created_at} for r in rows]
    out.sort(key=lambda a: (a["role"] != "owner", a["created_at"] is None,
                            a["created_at"].timestamp() if a["created_at"] else 0, a["name"] or ""))
    return out


def public_account(acc: dict) -> dict:
    """What the picker may show: no hashes, no data."""
    return {"id": str(acc["id"]), "name": acc["name"], "color": acc["color"],
            "role": acc["role"], "has_pin": bool(acc["pin_hash"])}


def _owner_of(accounts: list) -> Optional[dict]:
    return next((a for a in accounts if a["role"] == "owner"), None)


def _find(accounts: list, account_id) -> Optional[dict]:
    try:
        target = account_id if isinstance(account_id, uuid.UUID) else uuid.UUID(str(account_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return next((a for a in accounts if a["id"] == target), None)


# ── Server secret ────────────────────────────────────────────────────────────

_secret_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _engine_of(db):
    try:
        bind = db.get_bind()
    except Exception:
        return None
    return getattr(bind, "engine", bind)


def cookie_secret(db) -> bytes:
    """The HMAC key, created (and committed) on first use; cached per engine."""
    engine = _engine_of(db)
    if engine is not None and engine in _secret_cache:
        return _secret_cache[engine]
    from backend.accounts.settings import get_install_setting, put_setting
    value = (get_install_setting(db, SECRET_KEY) or "").strip()
    if not value:
        value = secrets.token_hex(32)
        try:
            put_setting(db, SECRET_KEY, value, account_id=None,
                        description="HMAC key that signs the jn_account cookie (generated)")
            db.commit()
        except Exception:
            # Another request created it first (unique install key): use theirs.
            db.rollback()
            value = (get_install_setting(db, SECRET_KEY) or "").strip()
            if not value:
                raise
    key = value.encode()
    if engine is not None:
        _secret_cache[engine] = key
    return key


def forget_secret_cache() -> None:
    _secret_cache.clear()


# ── Cookie ───────────────────────────────────────────────────────────────────

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_cookie(secret: bytes, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_cookie(secret: bytes, value: Optional[str]) -> Optional[dict]:
    """The payload of a well-signed, unexpired cookie, else None."""
    if not value or not isinstance(value, str) or value.count(".") != 1:
        return None
    body, sig = value.split(".")
    expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("e"), (int, float)):
        return None
    if payload["e"] < _now():
        return None
    return payload


def make_cookie_value(db, account: dict, unlocked_until: float = 0) -> str:
    payload = {"a": str(account["id"]), "p": pin_fingerprint(account["pin_hash"]),
               "e": int(_now() + COOKIE_MAX_AGE), "u": int(unlocked_until or 0)}
    return sign_cookie(cookie_secret(db), payload)


def set_account_cookie(response, db, account: dict, unlocked_until: float = 0) -> None:
    """Issue `jn_account` for `account` (also for MT-11 when a PIN change re-signs the
    caller's own cookie). Same flags and lifetime as jn_session."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=make_cookie_value(db, account, unlocked_until),
        httponly=True,
        samesite="strict",
        max_age=COOKIE_MAX_AGE,
        secure=False,  # set True when deployed over HTTPS (as jn_session)
    )


def clear_account_cookie(response) -> None:
    response.delete_cookie(key=COOKIE_NAME, samesite="strict", httponly=True)


def account_from_cookie(db, accounts: list, value: Optional[str]):
    """(account dict, payload) for a valid cookie of an existing account whose PIN has
    not changed since it was issued, else (None, None)."""
    if not value:
        return None, None
    payload = read_cookie(cookie_secret(db), value)
    if payload is None:
        return None, None
    acc = _find(accounts, payload.get("a"))
    if acc is None or payload.get("p", "") != pin_fingerprint(acc["pin_hash"]):
        return None, None
    return acc, payload


# ── Request resolution ───────────────────────────────────────────────────────

class Resolution:
    __slots__ = ("account", "error", "unlocked_until", "via")

    def __init__(self, account=None, error=None, unlocked_until=0, via=None):
        self.account = account
        self.error = error
        self.unlocked_until = unlocked_until
        self.via = via   # 'header' | 'cookie' | 'single' | None


def resolve_request(db, x_account: Optional[str], header_key_ok: bool, cookie: Optional[str]) -> Resolution:
    """Which account a request acts for (module docstring, layer 2).

    `header_key_ok`: the install key arrived in the X-API-Key header (or no key is
    configured). X-Account without it is ignored, so a browser holding only the
    jn_session cookie cannot pick an account without the PIN step."""
    accounts = load_accounts(db)
    if x_account and header_key_ok:
        acc = _find(accounts, x_account.strip())
        if acc is None:
            return Resolution(error=INVALID_ACCOUNT)
        return Resolution(account=acc, via="header")
    acc, payload = account_from_cookie(db, accounts, cookie)
    if acc is not None:
        return Resolution(account=acc, unlocked_until=float(payload.get("u") or 0), via="cookie")
    if len(accounts) == 1:
        return Resolution(account=accounts[0], via="single")
    if not accounts:
        return Resolution(via=None)    # before the MT-1 migration: run as before (owner fallback)
    return Resolution(error=ACCOUNT_REQUIRED)


# ── last_active_at (MT-11) ───────────────────────────────────────────────────

TOUCH_INTERVAL_SECONDS = 60.0
_touched: dict = {}   # str(account id) -> monotonic time of the last write


def touch_last_active(db, account_id, force: bool = False) -> bool:
    """Stamp `accounts.last_active_at = now` for an authenticated request, at most once a
    minute per account and process (in-memory throttle, so the hot path is a dict lookup).
    `force` (a switch) always writes. Never raises; returns whether it wrote."""
    if account_id is None:
        return False
    key = str(account_id)
    now = _mono()
    last = _touched.get(key)
    if not force and last is not None and now - last < TOUCH_INTERVAL_SECONDS:
        return False
    _touched[key] = now
    try:
        from datetime import datetime, timezone
        from sqlalchemy import update
        from backend.models.db import Account
        t = Account.__table__
        db.execute(update(t).where(t.c.id == account_id).values(last_active_at=datetime.now(timezone.utc)))
        db.commit()
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


def forget_touches() -> None:
    _touched.clear()


# ── PIN check for a switch, with per-account cooldown ────────────────────────

_pin_state: dict = {}   # str(account id) -> {"fails": int, "until": monotonic}


def reset_pin_cooldowns() -> None:
    _pin_state.clear()


def cooldown_left(account_id) -> float:
    st = _pin_state.get(str(account_id))
    if not st:
        return 0.0
    left = st["until"] - _mono()
    if left > 0:
        return left
    if st["until"]:
        _pin_state.pop(str(account_id), None)   # cooldown over: a fresh 5 tries
    return 0.0


def _record_failure(account_id) -> int:
    """Count a wrong PIN; returns tries left before the cooldown (0 = cooling down now)."""
    st = _pin_state.setdefault(str(account_id), {"fails": 0, "until": 0.0})
    st["fails"] += 1
    if st["fails"] >= PIN_MAX_FAILURES:
        st["fails"] = 0
        st["until"] = _mono() + PIN_COOLDOWN_SECONDS
        return 0
    return PIN_MAX_FAILURES - st["fails"]


def _clear(account_id) -> None:
    _pin_state.pop(str(account_id), None)


class SwitchDenied(Exception):
    def __init__(self, status: int, detail: str, retry_after: Optional[int] = None, tries_left=None):
        self.status = status
        self.detail = detail
        self.retry_after = retry_after
        self.tries_left = tries_left
        super().__init__(detail)


def _deny_cooling(account_id):
    left = cooldown_left(account_id)
    if left > 0:
        raise SwitchDenied(429, "pin_cooldown", retry_after=max(1, int(left + 0.999)))


def check_switch(accounts: list, target: dict, pin) -> str:
    """Raise SwitchDenied unless `pin` lets the caller into `target`. Returns how:
    'no_pin' | 'own_pin' | 'owner_pin'.

    * owner target: its PIN when one is set; none set yet -> allowed (MT-11/12 make the
      owner set one).
    * member target without a PIN -> allowed.
    * member target with a PIN -> its PIN, or the owner's PIN (when the owner has one and
      is not cooling down)."""
    owner = _owner_of(accounts)
    needs = bool(target["pin_hash"])
    if not needs:
        return "no_pin"
    _deny_cooling(target["id"])
    if pin is None or pin == "":
        raise SwitchDenied(401, "pin_required")
    if verify_pin(pin, target["pin_hash"]):
        _clear(target["id"])
        return "own_pin"
    covering = (owner is not None and target["role"] != "owner" and owner["pin_hash"]
                and cooldown_left(owner["id"]) <= 0)
    if covering and verify_pin(pin, owner["pin_hash"]):
        _clear(target["id"])
        _clear(owner["id"])
        return "owner_pin"
    left = _record_failure(target["id"])
    if covering:
        _record_failure(owner["id"])
    if left == 0:
        raise SwitchDenied(429, "pin_cooldown", retry_after=int(PIN_COOLDOWN_SECONDS))
    raise SwitchDenied(401, "wrong_pin", tries_left=left)


def check_owner_pin(accounts: list, pin) -> None:
    """For the 15-minute owner unlock: the owner's PIN (none set yet -> allowed), with
    the owner's cooldown."""
    owner = _owner_of(accounts)
    if owner is None:
        raise SwitchDenied(404, "no_owner")
    if not owner["pin_hash"]:
        return
    _deny_cooling(owner["id"])
    if pin is None or pin == "":
        raise SwitchDenied(401, "pin_required")
    if verify_pin(pin, owner["pin_hash"]):
        _clear(owner["id"])
        return
    left = _record_failure(owner["id"])
    if left == 0:
        raise SwitchDenied(429, "pin_cooldown", retry_after=int(PIN_COOLDOWN_SECONDS))
    raise SwitchDenied(401, "wrong_pin", tries_left=left)


# ── Route guard ──────────────────────────────────────────────────────────────

def require_owner():
    """FastAPI dependency: 403 for a member (install-level jobs: backup, H-1B refresh,
    LinkedIn session). Owner, system code and no-context callers pass."""
    from fastapi import HTTPException
    from backend.accounts.context import current_account, is_owner_unlocked, is_unscoped, owner_account_id
    if is_unscoped() or is_owner_unlocked():   # MT-14: the owner entered their PIN here
        return
    acc = current_account.get()
    if acc is None:
        return
    owner = owner_account_id()
    if owner is not None and acc != owner:
        raise HTTPException(status_code=403, detail="owner_only")
