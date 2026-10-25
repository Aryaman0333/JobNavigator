"""The employer's link for LinkedIn listings, looked up through the mock account.

Levels.fyi, Jobright and JobSpy hand over LinkedIn listings (`linkedin:<id>` keys, link kind
`board`). LinkedIn's public job page no longer names the employer's apply link; its logged-in
job API does (`companyApplyUrl`). This module asks it, once per LinkedIn job, through the mock
account's browser session that the extension import already uses, and never through the user's own
account: it refuses to run when that session is the personal account.

- One answer per LinkedIn job id, install-wide (`LinkedinLookup`), applied to every account's rows:
  `employer` (the link, followed when it is a short link), `easy_apply` (no employer link exists),
  `board` (LinkedIn names another board), `gone` (closed). Throttling and errors are not cached.
- One request every `pause` seconds (15), at most `per_run` per run; a run stops after LinkedIn
  answers nothing 3 times in a row.
- A row that gets an employer link is re-keyed, classified and relinked (posting_links.relink),
  so it joins the employer's posting the account already has.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from backend.scraper._shared.link_kinds import BOARD, DIRECT, EASY_APPLY, classify, link_kind

logger = logging.getLogger("jobnavigator.linkedin_lookup")

PAUSE = 15.0
STOP_AFTER_NO_DATA = 3


def mock_account_in_use(db) -> bool:
    """The extension session is the mock account's (refresh_linkedin_session._creds' rule)."""
    from backend.accounts.settings import get_setting
    switch = str(get_setting(db, "linkedin_use_mock_account") or "").strip().lower()
    has_mock = bool(str(get_setting(db, "linkedin_mock_email") or "").strip())
    return (switch or ("true" if has_mock else "false")) == "true"


def pending_ids(db, limit: int) -> list:
    """LinkedIn ids of rows still on a board link (any account), newest first."""
    from sqlalchemy import or_
    from backend.models.db import Job
    rows = (db.query(Job.posting_key)
            .filter(Job.posting_key.like("linkedin:%"),
                    or_(Job.link_kind == BOARD, Job.link_kind.is_(None)),
                    Job.status.notin_(("ignored", "duplicate")))
            .order_by(Job.discovered_at.desc()).limit(limit * 5).all())
    ids = list(dict.fromkeys(k.split(":", 1)[1] for (k,) in rows))
    return ids[:limit]


def apply_result(db, linkedin_id: str, apply_url, result: str) -> int:
    """Give every account's rows of this LinkedIn job the answer. Returns rows changed."""
    from sqlalchemy import or_
    from backend.models.db import Job
    from backend.scraper._shared.posting_links import key_of, relink
    rows = (db.query(Job)
            .filter(Job.posting_key == f"linkedin:{linkedin_id}",
                    or_(Job.link_kind.in_((BOARD, EASY_APPLY)), Job.link_kind.is_(None)),
                    Job.status != "ignored").all())
    if result == "employer" and apply_url:
        for job in rows:
            job.apply_url = apply_url
            job.posting_key = key_of(job)
            classify(job)
        db.flush()
        for job in rows:
            relink(db, job)
    elif result == EASY_APPLY:
        for job in rows:
            job.link_kind = EASY_APPLY
    else:
        return 0
    db.commit()
    return len(rows)


def _verdict(d):
    """(result, link) from one Voyager answer; None = no answer (counts toward the stop);
    ("unknown", None) = an answer that says nothing definite (not cached)."""
    if d is None:
        return None
    if d.get("apply_url"):
        return "employer", d["apply_url"]
    if str(d.get("job_state") or "").upper() == "CLOSED":
        return "gone", None
    if "Onsite" in str(d.get("apply_type") or ""):
        return EASY_APPLY, None
    return "unknown", None


@asynccontextmanager
async def _fetcher(fetch):
    """(fetch(lid) -> dict | None, None), or (None, why not) when there is no mock session."""
    if fetch is not None:
        yield fetch, None
        return
    from backend.accounts.background import acting_as
    from backend.models.db import SessionLocal
    from backend.scraper.sources import linkedin_extension as le
    with acting_as(None):
        sdb = SessionLocal()
        try:
            mock = mock_account_in_use(sdb)
        finally:
            sdb.close()
        cookies = le._load_session_cookies() if mock else None
    if not mock:
        yield None, "the LinkedIn session is not the mock account"
        return
    if not cookies:
        yield None, "no LinkedIn mock session"
        return
    from backend.scraper.sources.linkedin_personal import _get_linkedin_browser
    pw = browser = None
    try:
        pw, browser, context, page = await _get_linkedin_browser()
        # only the mock session: the helper may have loaded the personal scraper's cookies
        await context.clear_cookies()
        await context.add_cookies(cookies)
        await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=30000)

        async def fetch_one(lid):
            return await le._voyager_fetch(page, lid)
        yield fetch_one, None
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass


async def resolve_stored_short_links(limit: int = 50, resolve=None) -> int:
    """Stored jobs whose link is a short link (grnh.se, prng.co, appcast) and that have no employer
    link yet: follow it; a landing page that names an employer posting becomes `apply_url`, and
    the job is re-keyed, classified and relinked. A link that does not resolve waits for the next
    run. Returns the jobs that got their employer link."""
    from sqlalchemy import or_
    from backend.accounts.context import unscoped
    from backend.models.db import Job, SessionLocal
    from backend.scraper._shared.posting_links import employer_link, key_of, relink
    from backend.scraper._shared.postings import SHORT_LINK_HOSTS, is_short_link, resolve_short_link
    resolve = resolve or resolve_short_link
    done = 0
    # unscoped: install-level pass over every account's rows; relink names each row's account.
    with unscoped():
        db = SessionLocal()
        try:
            rows = (db.query(Job)
                    .filter(Job.apply_url.is_(None), Job.status != "ignored",
                            or_(*[Job.url.like(f"%{h}/%") for h in SHORT_LINK_HOSTS]))
                    .order_by(Job.discovered_at.desc()).limit(limit).all())
            for job in rows:
                if not is_short_link(job.url):
                    continue
                link = employer_link(await resolve(job.url))
                if not link:
                    continue
                job.apply_url = link
                job.posting_key = key_of(job)
                classify(job)
                db.flush()
                relink(db, job)
                db.commit()
                done += 1
        finally:
            db.close()
    return done


async def run_lookup(per_run: int, fetch=None, pause: float = PAUSE, resolve=None) -> dict:
    """One lookup run: every account's pending LinkedIn rows, then stored short links (install-level)."""
    out = await _linkedin_pass(per_run, fetch, pause, resolve)
    out["short_links"] = await resolve_stored_short_links(limit=50, resolve=resolve)
    logger.info(f"LinkedIn lookup: {out}")
    return out


async def _linkedin_pass(per_run: int, fetch, pause: float, resolve) -> dict:
    from backend.accounts.context import unscoped
    from backend.models.db import LinkedinLookup, SessionLocal
    from backend.scraper._shared.postings import resolve_short_link
    resolve = resolve or resolve_short_link
    out = {"looked_up": 0, "employer": 0, "easy_apply": 0, "board": 0, "gone": 0, "cached": 0, "stopped": None}
    # unscoped: an install-level pass over every account's rows; every query below and in
    # posting_links names the account it reads.
    with unscoped():
        db = SessionLocal()
        try:
            ids = pending_ids(db, limit=max(per_run * 5, 50))
            cached = {r.linkedin_id: r for r in
                      db.query(LinkedinLookup).filter(LinkedinLookup.linkedin_id.in_(ids)).all()} if ids else {}
            for lid in ids:
                if lid in cached:
                    apply_result(db, lid, cached[lid].apply_url, cached[lid].result)
                    out["cached"] += 1
            todo = [i for i in ids if i not in cached][:per_run]
            if not todo:
                return out
            async with _fetcher(fetch) as (fetch_one, why_not):
                if fetch_one is None:
                    out["stopped"] = why_not
                    logger.warning(f"LinkedIn lookup skipped: {why_not}")
                    return out
                misses = 0
                for n, lid in enumerate(todo):
                    if n and pause:
                        await asyncio.sleep(pause)
                    d = await fetch_one(lid)
                    out["looked_up"] += 1
                    verdict = _verdict(d)
                    if verdict is None:
                        misses += 1
                        if misses >= STOP_AFTER_NO_DATA:
                            out["stopped"] = f"no data from LinkedIn {STOP_AFTER_NO_DATA} times in a row"
                            break
                        continue
                    misses = 0
                    result, link = verdict
                    if result == "unknown":
                        continue
                    if result == "employer":
                        link = await resolve(link)
                        if link_kind(link, None) != DIRECT:
                            result = "board"
                    db.merge(LinkedinLookup(linkedin_id=lid, apply_url=link, result=result,
                                            job_state=(d.get("job_state") or None)))
                    db.commit()
                    apply_result(db, lid, link, result)
                    out[result] += 1
        finally:
            db.close()
    return out
