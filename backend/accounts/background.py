"""Background work per account (MT-7).

Scheduled jobs that touch account-owned rows run once per account: `for_each_account()`
lists the accounts (system read, `unscoped()`), then runs the job body under
`acting_as(account)` so every query sees that account's rows, every new row (JobRun,
ActivityLog, LlmCallLog, …) is stamped with it, and the monitor dedups the run under the
account's own key. One account failing does not stop the next.

Install-level jobs (DB backup, H-1B refresh, the scrape-health system alert) do not use
this; they keep running once, as the owner (`as_owner`).
"""
import logging
import uuid
from contextlib import contextmanager
from typing import Awaitable, Callable, Iterable, Optional

from backend.accounts.context import _unscoped, owner_account_id, unscoped, use_account

logger = logging.getLogger("jobnavigator.accounts")


def all_account_ids() -> list[Optional[uuid.UUID]]:
    """Every account id, the owner first, then members by creation time.

    If the accounts cannot be read (no accounts table yet, DB down) the list is `[None]`:
    the job then runs once in the owner fallback context, exactly as before MT-7."""
    from backend.models import db as db_mod
    from backend.models.db import Account
    try:
        s = db_mod.SessionLocal()
        try:
            with unscoped():
                rows = s.query(Account.id, Account.role, Account.created_at).all()
        finally:
            s.close()
    except Exception as e:
        logger.error("Could not list accounts, running as the owner only: %s", e)
        return [None]
    if not rows:
        return [None]
    rows.sort(key=lambda r: (r.role != "owner", r.created_at is None, r.created_at or 0))
    return [r.id for r in rows]


def gmail_account_ids() -> list[Optional[uuid.UUID]]:
    """Accounts the email check runs for (MT-19): the owner, as before (its own connected
    token, else GMAIL_REFRESH_TOKEN from .env; with neither the check returns at once without
    calling Google), plus every member with a connected token not marked expired."""
    ids = all_account_ids()
    if ids == [None] or len(ids) == 1:
        return ids[:1]
    from backend.email_monitor.gmail_auth import connected_member_ids
    from backend.models import db as db_mod
    try:
        s = db_mod.SessionLocal()
        try:
            members = connected_member_ids(s)
        finally:
            s.close()
    except Exception as e:
        logger.error("Could not read members' Gmail tokens, checking the owner only: %s", e)
        return ids[:1]
    return ids[:1] + [i for i in ids[1:] if i in members]


@contextmanager
def acting_as(account_id: Optional[uuid.UUID]):
    """Run the block as `account_id`, scoped even when the caller was `unscoped()`.
    None = the owner (no accounts readable, or a row with no account): QA F4 / R1-06 —
    it also clears `unscoped()` and sets the owner explicitly, so the body never runs
    over every account. With no owner at all (no accounts table yet) the block runs
    with no account context: the non-strict fallback then reads unfiltered, which is
    the pre-migration single-user behaviour."""
    token = _unscoped.set(False)
    try:
        if account_id is None:
            account_id = owner_account_id()
        with use_account(account_id):
            yield
    finally:
        _unscoped.reset(token)


async def for_each_account(
    label: str,
    body: Callable[[], Awaitable[None]],
    account_ids: Optional[Iterable[Optional[uuid.UUID]]] = None,
) -> None:
    """Await `body()` once per account (default: every account) under `acting_as(id)`.

    A failure is logged with its account and the loop goes on; afterwards the first
    failure is re-raised so APScheduler still logs the job as failed. The settings the
    body reads are read inside the loop, so account-scoped settings (MT-9) need no change
    here."""
    import backend.job_monitor as jm
    ids = list(account_ids) if account_ids is not None else all_account_ids()
    first_error: Optional[BaseException] = None
    # QA F3 / R2-08: the sweep registers the accounts it will visit, so an account
    # removal sees it as busy for them; an account being removed is skipped.
    with jm.fanning_out(ids):
        for acc in ids:
            if jm.is_removing(acc):
                logger.info("%s skipped for account %s: it is being removed", label, acc)
                continue
            try:
                with acting_as(acc):
                    await body()
            except Exception as e:
                # The first failure is re-raised below (and logged with its traceback by
                # APScheduler); later ones only exist here, so they carry their own.
                logger.error("%s failed for account %s: %s", label, acc or "owner", e,
                             exc_info=first_error is not None)
                if first_error is None:
                    first_error = e
    if first_error is not None:
        raise first_error
