"""Shared-scrape targets (MT-8).

Every account keeps its own searches and companies, but two of them that would fetch
exactly the same thing are one *target*: the scheduler fetches it once and hands the raw
postings to each subscriber, whose own ingest (title/company filters, excludes, dedup,
H-1B and salary checks, auto-score) runs under its own account context.

Target keys
- Company: the set of normalised scrape URLs (+ the ATS each one is detected as),
  max_pages and wait_for_selector. A different URL, e.g. a city filter in the query
  string, is a different target.
- Search, by mode:
  - keyword (JobSpy): boards, term, location, country, job type, remote flag.
    results_wanted and hours_old are NOT part of the key: the shared fetch uses the
    largest value among subscribers and each account trims its copy afterwards.
  - levels_fyi: normalised direct_url + max_pages.
  - freehire: the API query the search builds (direct_url filters + term); results_wanted
    is taken as the max and trimmed per account.
  - linkedin_personal, jobright and anything unknown read the account's own session, so
    they are never shared: their key carries the search id.

Due-ness: a target is due when any subscriber is due under its own interval (custom, or
the global default), so the effective interval is the shortest among subscribers. A due
target feeds every subscriber. A manual "run now" on one search/company does not use this
module: it fetches for, and feeds, only the account that pressed it.

Everything here is pure (no DB writes); loading rows across accounts is the caller's job
(`load_active`), done inside `unscoped()`.
"""
import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.accounts.context import unscoped

logger = logging.getLogger("jobnavigator.scraper.targets")

EXTENSION_MODES = ("linkedin_extension", "extension")
# Modes whose fetch depends on the account's own login/session, never shared.
_PER_ACCOUNT_MODES = ("linkedin_personal", "jobright")


# ── Shared fetch ─────────────────────────────────────────────────────────────

class SharedFetch:
    """The one fetch of a shared target, memoised for its subscribers.

    The first subscriber's run performs the fetch through `get()` / `get_sync()`; later
    subscribers get a deep copy of the same postings (or the same exception), so an ingest
    can never change what the next account sees. Subscribers run one after another (the
    scrape has one global concurrency limit), so no lock is needed.

    `params` holds the fetch-side values that differ from a subscriber's own, e.g.
    {"results_wanted": 200, "hours_old": 72} (the max among subscribers)."""

    def __init__(self, key=None, params: Optional[dict] = None):
        self.key = key
        self.params = dict(params or {})
        self.done = False
        self.calls = 0           # how many times the fetch really ran (0 or 1)
        self.duration = 0.0
        self._value = None
        self._error: Optional[BaseException] = None

    def _result(self):
        if self._error is not None:
            raise self._error
        return copy.deepcopy(self._value)

    async def get(self, fetch: Callable[[], Any]):
        if not self.done:
            start = time.time()
            self.calls += 1
            try:
                self._value = await fetch()
            except Exception as e:
                self._error = e
            self.duration = time.time() - start
            self.done = True
        return self._result()

    def get_sync(self, fetch: Callable[[], Any]):
        if not self.done:
            start = time.time()
            self.calls += 1
            try:
                self._value = fetch()
            except Exception as e:
                self._error = e
            self.duration = time.time() - start
            self.done = True
        return self._result()


# ── Keys ─────────────────────────────────────────────────────────────────────

def target_url(url: str) -> str:
    """A list/board URL in comparable form: trimmed, scheme and host lowercased, no
    fragment, no trailing slash, tracking params (utm_* and the `dedup_tracking_params`
    setting) dropped, remaining query params sorted. Path case and every other query
    param (a city filter, a department) are kept: they change what is fetched."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        return raw   # a request spec such as "POST|https://…|{json}": compared verbatim
    try:
        from backend.scraper._shared.dedup import _get_tracking_params
        tracking = _get_tracking_params()
    except Exception:
        tracking = set()
    try:
        parts = urlsplit(raw)
        query = sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in tracking
        )
        path = parts.path.rstrip("/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                           urlencode(query, doseq=True), ""))
    except Exception:
        return raw


def _ats_label(url: str) -> str:
    try:
        from backend.api.routes_companies import detect_scrape_type
        return detect_scrape_type(url)
    except Exception:
        return "?"


def company_key(company) -> tuple:
    urls = sorted({target_url(u) for u in (company.scrape_urls or []) if (u or "").strip()})
    return (
        "company",
        tuple((u, _ats_label(u)) for u in urls),
        getattr(company, "max_pages", 5) or 5,
        (getattr(company, "wait_for_selector", None) or "").strip(),
    )


def _norm(text) -> str:
    return " ".join(str(text or "").split()).lower()


def search_key(search) -> tuple:
    mode = search.search_mode or "keyword"
    if mode == "keyword":
        from backend.countries import DEFAULT_COUNTRY
        return (
            "keyword",
            tuple(sorted({s for s in (search.sources or []) if s != "direct"})),
            _norm(search.search_term),
            _norm(search.location),
            _norm(search.country or DEFAULT_COUNTRY),
            _norm(search.job_type or "fulltime"),
            search.is_remote,
        )
    if mode == "levels_fyi":
        return ("levels_fyi", target_url(search.direct_url), search.max_pages or 50)
    if mode == "freehire":
        from backend.scraper.sources.freehire import _base_params
        return ("freehire", tuple(sorted(_base_params(search).items())))
    # linkedin_personal / jobright (the account's own session) and unknown modes
    return (mode, "own", str(search.id))


def search_fetch_params(subscribers: list) -> dict:
    """The fetch-side values for a shared search target: the max of the trimmed fields."""
    mode = subscribers[0].search_mode or "keyword"
    if mode == "keyword":
        return {
            "results_wanted": max((s.results_wanted or 50) for s in subscribers),
            "hours_old": max((s.hours_old or 24) for s in subscribers),
        }
    if mode == "freehire":
        return {"results_wanted": max((s.results_wanted or 100) for s in subscribers)}
    return {}


def is_shareable_search(search) -> bool:
    return (search.search_mode or "keyword") in ("keyword", "levels_fyi", "freehire")


# ── Due-ness ─────────────────────────────────────────────────────────────────

def _as_utc(ts):
    if ts is not None and ts.tzinfo is None:   # SQLite / legacy rows are naive UTC
        return ts.replace(tzinfo=timezone.utc)
    return ts


def company_due(company, now: datetime, global_interval: int):
    """(due, elapsed_minutes|None, interval) for one company under its own interval."""
    interval = company.scrape_interval_minutes or global_interval
    last = _as_utc(company.last_scraped_at)
    if not last:
        return True, None, interval
    elapsed = (now - last).total_seconds() / 60
    return elapsed >= interval, elapsed, interval


def search_due(search, now: datetime):
    """(due, elapsed_minutes|None, interval). A search without its own interval runs on
    every scheduler tick (the global scrape interval), as before."""
    interval = search.run_interval_minutes or 0
    last = _as_utc(search.last_run_at)
    if not interval or not last:
        return True, None, interval
    elapsed = (now - last).total_seconds() / 60
    return elapsed >= interval, elapsed, interval


# ── Targets ──────────────────────────────────────────────────────────────────

@dataclass
class Target:
    key: tuple
    subscribers: list = field(default_factory=list)   # Search or Company rows, load order

    @property
    def shared(self) -> bool:
        return len(self.subscribers) > 1

    @property
    def account_ids(self) -> list:
        out = []
        for s in self.subscribers:
            if s.account_id not in out:
                out.append(s.account_id)
        return out


def group_targets(rows: list, key_fn: Callable) -> list[Target]:
    """Group rows by key, keeping the order in which each key first appears (so a single
    account without duplicates iterates exactly as the rows were loaded)."""
    targets: dict = {}
    for row in rows:
        try:
            key = key_fn(row)
        except Exception as e:   # a key we cannot build is a target of its own
            logger.warning(f"Target key failed for {getattr(row, 'name', row)!r}: {e}")
            key = ("unkeyed", str(getattr(row, "id", id(row))))
        targets.setdefault(key, Target(key=key)).subscribers.append(row)
    return list(targets.values())


def company_target_due(target: Target, now: datetime, global_interval: int):
    """(due, effective_interval). Due when any subscriber is due; the effective interval
    is the shortest among subscribers."""
    states = [company_due(c, now, global_interval) for c in target.subscribers]
    return any(s[0] for s in states), min(s[2] for s in states)


def search_target_due(target: Target, now: datetime):
    states = [search_due(s, now) for s in target.subscribers]
    return any(s[0] for s in states), min(s[2] for s in states)


def load_active(db, model, account_ids=None) -> list:
    """Active rows of `model` for the given accounts (None = every account), read
    `unscoped()` so one pass sees every subscriber. An id list holding only None (the
    owner fallback when accounts are unreadable) reads in the caller's context."""
    q = db.query(model).filter(model.active == True)  # noqa: E712
    if account_ids is None:
        with unscoped():
            return q.all()
    ids = [a for a in account_ids if a is not None]
    if not ids:
        return q.all()
    with unscoped():
        return q.filter(model.account_id.in_(ids)).all()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
