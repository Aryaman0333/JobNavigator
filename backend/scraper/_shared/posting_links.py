"""Link a new job to the posting it repeats, for every source at once.

A job is stored once per link (`external_id`), so one posting reached through Jobright,
Levels.fyi, LinkedIn and the company's own board became four feed rows. Every new Job
now gets a `posting_key` (postings.py) from its employer link (`apply_url`) or its own
link, and before it is written it is compared with the account's jobs:

1. Same posting key as a job the feed already has: the newcomer is that posting again.
2. No employer key of its own (a LinkedIn or Indeed listing, or an unknown site), and a
   job with an employer key, the same company and title (`content_hash`), found in the
   last 30 days: the listing is a copy of that posting.
3. The reverse of 2: the newcomer is the employer's posting and the feed holds an
   untouched (status "new") listing-only copy from the last 30 days: that copy is the
   duplicate from now on.

A duplicate is kept, not dropped: status "duplicate", `duplicate_of` pointing at the
posting, so its link stays known (no re-import), the feed hides it, and the original
lists it under "Also on". Rows the user acted on (saved, applied, skipped) are never
turned into duplicates. Filtered rows ("ignored") are neither linked nor link targets.

This runs in a before_flush listener registered after the account stamping
(accounts/scoping.py), so `account_id` is already set; every query names the account.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from backend.scraper._shared.postings import is_employer_key, posting_key, unwrap

logger = logging.getLogger("jobnavigator.posting_links")

DUPLICATE = "duplicate"
NOT_TARGETS = ("ignored", DUPLICATE)
TITLE_MATCH_DAYS = 30


def keys_of(job) -> list:
    """Every posting key the job's links name, the employer's first (an Indeed row names both
    its listing and, through `apply_url`, the employer's posting)."""
    keys = []
    for k in (posting_key(u) for u in (job.apply_url, job.url) if u):
        if k and k not in keys:
            keys.append(k)
    return sorted(keys, key=lambda k: not is_employer_key(k))


def key_of(job) -> str | None:
    """The job's posting key: the employer's posting when either link names one, else the listing."""
    keys = keys_of(job)
    return keys[0] if keys else None


def employer_link(url) -> str | None:
    """`url` as an employer link worth storing in `apply_url`: unwrapped, and naming an employer posting."""
    if not url:
        return None
    plain = unwrap(url)
    return plain if is_employer_key(posting_key(plain)) else None


def _visible(Job):
    return (Job.status.is_(None)) | (Job.status.notin_(NOT_TARGETS))


def _ensure_id(job):
    if job.id is None:
        job.id = uuid.uuid4()
    return job.id


def mark_duplicate(job, original) -> None:
    """`job` is `original` again: hide it under the original, and give the original the employer link it lacked."""
    job.status = DUPLICATE
    job.duplicate_of = _ensure_id(original)
    if job.posting_key and is_employer_key(job.posting_key) and not is_employer_key(original.posting_key):
        original.posting_key = job.posting_key
    if not original.apply_url:
        link = employer_link(job.apply_url) or employer_link(job.url)
        if link and link != original.url:
            original.apply_url = link


def _recent(Job):
    return Job.discovered_at >= datetime.now(timezone.utc) - timedelta(days=TITLE_MATCH_DAYS)


def find_original(session, job, batch: dict):
    """The job the account already has for this posting (rules 1 and 2), or None."""
    from backend.models.db import Job

    key, acct = job.posting_key, job.account_id
    keys = [k for k in dict.fromkeys([key] + keys_of(job)) if k]
    if keys:
        for k in keys:
            hit = batch.get((acct, k))
            if hit is not None and hit is not job:
                return hit
        q = (session.query(Job)
             .filter(Job.account_id == acct, Job.posting_key.in_(keys), _visible(Job)))
        if job.id is not None:
            q = q.filter(Job.id != job.id)
        hit = q.order_by(Job.discovered_at.asc()).first()
        if hit is not None:
            return hit
    if is_employer_key(key) or not job.content_hash:
        return None
    hit = batch.get((acct, "title", job.content_hash))
    if hit is not None and hit is not job:
        return hit
    return (session.query(Job)
            .filter(Job.account_id == acct, Job.content_hash == job.content_hash, _visible(Job),
                    Job.posting_key.isnot(None), ~Job.posting_key.like("linkedin:%"),
                    ~Job.posting_key.like("indeed:%"), _recent(Job))
            .order_by(Job.discovered_at.desc()).first())


def listing_copies(session, job) -> list:
    """Rule 3: untouched listing-only copies of an employer posting that just arrived."""
    from backend.models.db import Job

    if not is_employer_key(job.posting_key) or not job.content_hash:
        return []
    q = (session.query(Job)
         .filter(Job.account_id == job.account_id, Job.content_hash == job.content_hash,
                 Job.status == "new", _recent(Job),
                 Job.posting_key.is_(None) | Job.posting_key.like("linkedin:%")
                 | Job.posting_key.like("indeed:%")))
    if job.id is not None:
        q = q.filter(Job.id != job.id)
    return q.all()


def link_new_jobs(session, flush_context=None, instances=None) -> None:
    """before_flush: give every new Job its posting key and link it to the posting it repeats."""
    from backend.models.db import Job

    new = [o for o in session.new if isinstance(o, Job)]
    if not new:
        return
    batch: dict = {}
    with session.no_autoflush:
        for job in new:
            if job.posting_key is None:
                job.posting_key = key_of(job)
            if job.apply_url is None:
                link = employer_link(job.url)
                if link and link != job.url:
                    job.apply_url = link
        for job in new:
            if job.status in NOT_TARGETS or job.duplicate_of is not None or job.account_id is None:
                continue
            try:
                original = find_original(session, job, batch)
                if original is not None:
                    mark_duplicate(job, original)
                    continue
                for copy in listing_copies(session, job):
                    mark_duplicate(copy, job)
            except Exception as e:  # linking must never stop a job from being stored
                logger.warning(f"Posting link skipped for {job.title!r} at {job.company!r}: {e}")
                continue
            for k in dict.fromkeys([job.posting_key] + keys_of(job)):
                if k:
                    batch.setdefault((job.account_id, k), job)
            if job.content_hash and is_employer_key(job.posting_key):
                batch.setdefault((job.account_id, "title", job.content_hash), job)


def install_posting_links() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    event.listen(Session, "before_flush", link_new_jobs)


def counts_as_new(job) -> bool:
    """For a source's "+N new": a job stored as a duplicate is not new to the feed."""
    return getattr(job, "status", None) != DUPLICATE
