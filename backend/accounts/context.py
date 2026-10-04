"""The account a piece of code acts for (MT-2).

`current_account` holds the id of the account whose rows every ORM query sees and
every new row belongs to (see `backend.accounts.scoping`). Request code gets it from
the HTTP middleware; background code wraps its entry point in `use_account(id)` or
`as_owner(...)`. System code that must see every account (backups, migrations, the
scheduler fan-out) runs inside `unscoped()` — keep that call grep-able.

When nothing set the context: with `MT_STRICT=1` (tests) a query on an account-owned
model raises `AccountContextMissing`; otherwise it falls back to the owner account, so
a single-user install behaves exactly as before.
"""
import functools
import logging
import os
import uuid
import weakref
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger("jobnavigator.accounts")

current_account: ContextVar[Optional[uuid.UUID]] = ContextVar("jn_current_account", default=None)
_unscoped: ContextVar[bool] = ContextVar("jn_unscoped", default=False)


class AccountContextMissing(RuntimeError):
    """An account-owned model was queried or written with no account context (strict mode)."""


def _as_uuid(value) -> Optional[uuid.UUID]:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


@contextmanager
def use_account(account_id):
    """Run the block as `account_id` (None clears the context)."""
    token = current_account.set(_as_uuid(account_id))
    try:
        yield
    finally:
        current_account.reset(token)


@contextmanager
def unscoped():
    """Escape hatch for system code: queries see every account's rows. New rows are still
    stamped with the current account, or the owner when none is set."""
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)


def is_unscoped() -> bool:
    return _unscoped.get()


def strict_mode() -> bool:
    return os.environ.get("MT_STRICT", "").strip().lower() in ("1", "true", "yes")


# ── Owner id, cached per engine (it never changes; tests rebind the engine) ──
_owner_ids: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _engine_of(bind):
    return getattr(bind, "engine", bind)


def remember_owner(bind, owner_id) -> None:
    """Prime the cache (tests create the owner themselves)."""
    _owner_ids[_engine_of(bind)] = _as_uuid(owner_id)


def forget_owner_cache() -> None:
    _owner_ids.clear()


def owner_id_for_session(session) -> Optional[uuid.UUID]:
    """The owner account of the database `session` talks to, or None before the migration
    has created it. Uses a Core select on the session's connection, so no ORM events fire."""
    try:
        engine = _engine_of(session.get_bind())
    except Exception:
        return None
    cached = _owner_ids.get(engine)
    if cached is not None:
        return cached
    from sqlalchemy import select
    from backend.models.db import Account
    t = Account.__table__
    try:
        row = session.connection().execute(
            select(t.c.id).where(t.c.role == "owner").order_by(t.c.created_at).limit(1)
        ).first()
    except Exception as e:  # accounts table missing (partial test schemas)
        logger.debug("owner lookup failed: %s", e)
        return None
    owner = _as_uuid(row[0]) if row else None
    if owner is not None:
        _owner_ids[engine] = owner
    return owner


def owner_account_id() -> Optional[uuid.UUID]:
    """The owner id for the app's own SessionLocal (middleware, background entry points)."""
    from backend.models import db as db_mod
    engine = _engine_of(db_mod.SessionLocal.kw.get("bind"))
    cached = _owner_ids.get(engine) if engine is not None else None
    if cached is not None:
        return cached
    s = db_mod.SessionLocal()
    try:
        return owner_id_for_session(s)
    finally:
        s.close()


def resolve_account(session) -> Optional[uuid.UUID]:
    """The account a statement runs for: the context, else (non-strict) the owner."""
    acc = current_account.get()
    if acc is not None:
        return acc
    if strict_mode():
        raise AccountContextMissing(
            "No account context: wrap the code in use_account(...) or unscoped() (MT_STRICT=1)")
    return owner_id_for_session(session)


def owner_context():
    """`use_account(owner)` when no account is set yet, else a no-op. For entry points of
    background work (scheduler jobs, tracked runs, launched tasks) until MT-7 runs them
    per account."""
    if current_account.get() is not None or is_unscoped():
        return nullcontext()
    try:
        owner = owner_account_id()
    except Exception as e:
        logger.warning("owner lookup failed, running without an account context: %s", e)
        return nullcontext()
    return use_account(owner) if owner is not None else nullcontext()


def as_owner(func):
    """Decorate an async entry point so it runs in the owner context when none is set."""
    @functools.wraps(func)
    async def _wrapped(*args, **kwargs):
        with owner_context():
            return await func(*args, **kwargs)
    return _wrapped
