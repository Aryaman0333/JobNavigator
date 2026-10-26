"""linkedin_lookup.py: LinkedIn listings get the employer's link through the mock account (direct-links plan)."""
import pytest

from backend.models.db import Account, Job, LinkedinLookup, Setting
from backend.scraper._shared import linkedin_lookup as ll
from backend.tests.test_posting_links import _job

GH = "https://job-boards.greenhouse.io/acme/jobs/4012345"
LI = "https://www.linkedin.com/jobs/view/{}"


def _li(db, lid="4461186967", **kw):
    kw.setdefault("company", "Acme")
    kw.setdefault("title", "PM")
    return _job(db, LI.format(lid), source="levels_fyi", **kw)


class FakeLinkedIn:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def __call__(self, lid):
        self.calls.append(lid)
        return self.answers.get(lid)


async def _no_resolve(url):
    return url


@pytest.fixture
def mock_jar(tmp_path, monkeypatch):
    """Both LinkedIn jars in a temp dir; `ready(db, cookies=, signed=)` sets the mock account up."""
    import json as _json
    from backend import refresh_linkedin_session as rls
    from backend.accounts import credentials as C
    monkeypatch.setattr(C, "LI_EXTENSION_OWNER", str(tmp_path / "li_cookies.json"))
    monkeypatch.setattr(C, "LI_PERSONAL_OWNER", str(tmp_path / "linkedin_cookies.json"))

    def ready(db, cookies=True, signed=True):
        db.add(Setting(key="linkedin_mock_email", value="mock@x.io"))
        db.commit()
        if cookies:
            with open(rls.jar(rls.MOCK), "w") as f:
                _json.dump([{"name": "li_at", "value": "x", "domain": ".linkedin.com", "path": "/"}], f)
        if signed:
            rls.record_sign_in(rls.MOCK, "mock@x.io")
    return ready


async def _run(fetch, per_run=20, resolve=_no_resolve):
    return await ll.run_lookup(per_run=per_run, fetch=fetch, pause=0, resolve=resolve)


@pytest.mark.asyncio
async def test_an_employer_link_becomes_the_apply_link(test_db):
    job = _li(test_db)
    assert job.link_kind == "board"
    fake = FakeLinkedIn({"4461186967": {"apply_url": GH, "apply_type": "OffsiteApply", "job_state": "LISTED"}})
    out = await _run(fake)
    test_db.refresh(job)
    assert job.apply_url == GH and job.posting_key == "greenhouse:4012345" and job.link_kind == "direct"
    assert out["employer"] == 1
    assert test_db.get(LinkedinLookup, "4461186967").result == "employer"


@pytest.mark.asyncio
async def test_the_job_joins_the_employer_posting_it_names(test_db):
    posting = _job(test_db, GH, company="Acme", title="Product Manager", source="direct")
    job = _li(test_db)
    await _run(FakeLinkedIn({"4461186967": {"apply_url": GH, "apply_type": "OffsiteApply"}}))
    test_db.refresh(job)
    assert job.status == "ignored" and job.duplicate_of == posting.id


@pytest.mark.asyncio
async def test_easy_apply_is_recorded(test_db):
    job = _li(test_db)
    await _run(FakeLinkedIn({"4461186967": {"apply_url": "", "apply_type": "ComplexOnsiteApply"}}))
    test_db.refresh(job)
    assert job.link_kind == "easy_apply"
    assert test_db.get(LinkedinLookup, "4461186967").result == "easy_apply"


@pytest.mark.asyncio
async def test_a_cached_id_is_never_fetched_again(test_db):
    test_db.add(LinkedinLookup(linkedin_id="4461186967", apply_url=GH, result="employer"))
    test_db.commit()
    job = _li(test_db)
    fake = FakeLinkedIn({})
    await _run(fake)
    test_db.refresh(job)
    assert fake.calls == [] and job.apply_url == GH and job.link_kind == "direct"


@pytest.mark.asyncio
async def test_no_data_is_not_cached_and_three_in_a_row_stop_the_run(test_db):
    for i in range(5):
        _li(test_db, lid=f"446118696{i}", title=f"PM {i}")
    fake = FakeLinkedIn({})
    out = await _run(fake)
    assert len(fake.calls) == 3
    assert out["stopped"] == "no data from LinkedIn 3 times in a row"
    assert test_db.query(LinkedinLookup).count() == 0


@pytest.mark.asyncio
async def test_lookup_follows_a_short_employer_link(test_db):
    job = _li(test_db)

    async def resolve(url):
        return GH if url == "https://grnh.se/abc" else url
    await _run(FakeLinkedIn({"4461186967": {"apply_url": "https://grnh.se/abc", "apply_type": "OffsiteApply"}}),
               resolve=resolve)
    test_db.refresh(job)
    assert job.apply_url == GH and job.posting_key == "greenhouse:4012345"


@pytest.mark.asyncio
async def test_lookup_without_a_session_does_nothing(test_db, mock_jar):
    mock_jar(test_db, cookies=False)
    job = _li(test_db)
    out = await ll.run_lookup(per_run=20, pause=0)
    test_db.refresh(job)
    assert out["stopped"] == "no LinkedIn mock session"
    assert job.link_kind == "board"


@pytest.mark.asyncio
async def test_lookup_needs_a_mock_account(test_db, mock_jar):
    _li(test_db)
    out = await ll.run_lookup(per_run=20, pause=0)
    assert out["stopped"] == "no mock account is set (Settings › LinkedIn)"


@pytest.mark.asyncio
async def test_lookup_needs_the_mock_accounts_own_sign_in(test_db, mock_jar):
    """A jar saved before the sessions were split (or by the main sign-in) proves nothing."""
    from backend import refresh_linkedin_session as rls
    mock_jar(test_db, signed=False)
    _li(test_db)
    out = await ll.run_lookup(per_run=20, pause=0)
    assert out["stopped"] == "the mock session has no sign-in record: sign the mock account in (Settings › LinkedIn)"
    rls.record_sign_in(rls.MAIN, "me@x.io")
    assert (await ll.run_lookup(per_run=20, pause=0))["stopped"].startswith("the mock session has no sign-in record")


@pytest.mark.asyncio
async def test_one_lookup_updates_every_account(test_db):
    from backend.accounts.context import use_account
    mine = _li(test_db)
    mine_id = mine.id
    partner = Account(name="Partner", role="member")
    test_db.add(partner)
    test_db.commit()
    with use_account(partner.id, test_db):
        theirs_id = _li(test_db).id
    fake = FakeLinkedIn({"4461186967": {"apply_url": GH, "apply_type": "OffsiteApply"}})
    await _run(fake)
    from backend.accounts.context import unscoped
    with unscoped():
        test_db.expire_all()
        mine = test_db.query(Job).filter(Job.id == mine_id).one()
        theirs = test_db.query(Job).filter(Job.id == theirs_id).one()
        assert fake.calls == ["4461186967"]
        assert mine.link_kind == theirs.link_kind == "direct"
        assert theirs.account_id == partner.id


@pytest.mark.asyncio
async def test_rows_with_an_employer_link_are_not_looked_up(test_db):
    _job(test_db, "https://www.indeed.com/viewjob?jk=0362e90102d8ac2c", apply_url=GH, source="jobspy_indeed")
    _job(test_db, LI.format("4461186967"), apply_url="https://jobs.lever.co/acme/1cafb489-9cae-4417-b272-832617484de0")
    fake = FakeLinkedIn({})
    await _run(fake)
    assert fake.calls == []


@pytest.mark.asyncio
async def test_a_row_the_user_acted_on_keeps_its_status(test_db):
    _job(test_db, GH, company="Acme", title="Product Manager", source="direct")
    saved = _li(test_db, status="saved")
    await _run(FakeLinkedIn({"4461186967": {"apply_url": GH, "apply_type": "OffsiteApply"}}))
    test_db.refresh(saved)
    assert saved.status == "saved" and saved.duplicate_of is None and saved.link_kind == "direct"


@pytest.mark.asyncio
async def test_a_closed_job_is_gone(test_db):
    job = _li(test_db)
    await _run(FakeLinkedIn({"4461186967": {"apply_url": "", "apply_type": "", "job_state": "CLOSED"}}))
    test_db.refresh(job)
    assert job.link_kind == "board"
    assert test_db.get(LinkedinLookup, "4461186967").result == "gone"


def test_the_lookup_has_no_settings_of_its_own():
    """It runs after every scrape, at a fixed pace: the 3.2 cron and per-run settings are gone."""
    from backend.seed import DEFAULT_SETTINGS
    from backend.accounts.settings import KEY_SECTION
    for key in ("linkedin_lookup_cron", "linkedin_lookup_per_run"):
        assert key not in DEFAULT_SETTINGS and key not in KEY_SECTION
    assert ll.PAUSE == 2.0


def test_the_lookup_is_not_a_schedule(test_db, monkeypatch):
    import backend.scheduler as sched_mod

    class Recorder:
        def __init__(self):
            self.ids = []

        def add_job(self, func, trigger, id, replace_existing):
            self.ids.append(id)

        def remove_all_jobs(self):
            pass

        def get_jobs(self):
            return self.ids
    rec = Recorder()
    monkeypatch.setattr(sched_mod, "scheduler", rec)
    sched_mod.configure_scheduler()
    assert "linkedin_lookup" not in rec.ids


@pytest.mark.asyncio
async def test_a_finished_scrape_starts_the_lookup(monkeypatch):
    import asyncio
    import uuid
    from datetime import datetime, timezone
    from backend import job_monitor as jm

    started = []

    async def lookup():
        started.append(True)

    monkeypatch.setattr(jm, "_restart_job_run", lambda *a: None)
    monkeypatch.setattr(jm, "_after_scrape_hooks", [lookup])

    class Running:
        waiting = False
        started_at = datetime.now(timezone.utc)
        run_id = uuid.uuid4()

    async with jm._gated(jm.limiter_for_job_type("search_run"), Running()):
        pass
    async with jm._gated(jm.limiter_for_job_type("analyze_job"), Running()):
        pass
    await asyncio.sleep(0)
    assert started == [True]   # once: after the scrape, not after the scoring run


@pytest.mark.asyncio
async def test_after_a_scrape_nothing_pending_means_no_run(test_db, monkeypatch):
    from backend import scheduler as sched_mod
    runs = []

    async def fake_run_lookup(**kw):
        runs.append(kw)
        return {}
    monkeypatch.setattr("backend.scraper._shared.linkedin_lookup.run_lookup", fake_run_lookup)
    await sched_mod.lookup_after_scrape()
    assert runs == []


def test_the_voyager_call_reports_how_the_job_is_applied_to():
    from backend.scraper.sources.linkedin_extension import _VOYAGER_JOB_JS
    assert "apply_type" in _VOYAGER_JOB_JS and "job_state" in _VOYAGER_JOB_JS


@pytest.mark.asyncio
async def test_a_stored_grnh_se_link_is_followed(test_db):
    posting = _job(test_db, GH, company="Acme", title="Product Manager", source="direct")
    short = _job(test_db, "https://grnh.se/zvej33q44us", company="Acme", title="PM", source="levels_fyi")

    async def resolve(url):
        return GH if "grnh.se" in url else url
    n = await ll.resolve_stored_short_links(limit=50, resolve=resolve)
    test_db.refresh(short)
    assert n == 1
    assert short.apply_url == GH and short.posting_key == "greenhouse:4012345"
    assert short.status == "ignored" and short.duplicate_of == posting.id


@pytest.mark.asyncio
async def test_an_unresolved_short_link_is_left_alone(test_db):
    short = _job(test_db, "https://grnh.se/zvej33q44us", company="Acme", title="PM", source="levels_fyi")
    n = await ll.resolve_stored_short_links(limit=50, resolve=_no_resolve)
    test_db.refresh(short)
    assert n == 0 and short.apply_url is None and short.posting_key is None


@pytest.mark.asyncio
async def test_the_lookup_run_also_follows_short_links(test_db):
    _job(test_db, "https://grnh.se/zvej33q44us", company="Acme", title="PM", source="levels_fyi")

    async def resolve(url):
        return GH if "grnh.se" in url else url
    out = await _run(FakeLinkedIn({}), resolve=resolve)
    assert out["short_links"] == 1


def _fake_browser(monkeypatch, landed: str, me: int, li_at: bool = True):
    # the mock jar and its sign-in record come from the `mock_jar` fixture
    """The lookup's browser, faked: where opening the feed lands, what /voyager/api/me answers,
    and whether the jar holds `li_at`. Returns the list of Voyager job requests made."""
    from backend.scraper.sources import linkedin_extension as le
    from backend.scraper.sources import linkedin_personal as lp
    asked = []

    class Page:
        url = ""

        async def goto(self, url, **k):
            self.url = landed

        async def evaluate(self, js, *args):
            if args:                      # a Voyager job request (the job id is the argument)
                asked.append(args[0])
                return {"status": 200, "apply_url": GH, "apply_type": "OffsiteApply"}
            return me                     # /voyager/api/me

    class Ctx:
        async def clear_cookies(self):
            pass

        async def add_cookies(self, c):
            pass

        async def cookies(self):
            return [{"name": "li_at", "value": "x"}] if li_at else []

    class Closable:
        async def close(self):
            pass

        async def stop(self):
            pass

    async def fake_browser():
        return Closable(), Closable(), Ctx(), Page()

    monkeypatch.setattr(lp, "_get_linkedin_browser", fake_browser)
    return asked


@pytest.mark.asyncio
async def test_an_expired_mock_session_stops_before_any_request(test_db, monkeypatch, mock_jar):
    """LinkedIn signed the mock session out: the feed redirects to the login page."""
    mock_jar(test_db)
    job = _li(test_db)
    asked = _fake_browser(monkeypatch, "https://www.linkedin.com/uas/login?session_redirect=x", 401)
    out = await ll.run_lookup(per_run=20, pause=0)
    test_db.refresh(job)
    assert out["stopped"] == "the LinkedIn mock session is signed out: sign it in again in Settings › LinkedIn"
    assert asked == [] and job.link_kind == "board"


@pytest.mark.asyncio
async def test_a_live_session_whose_me_call_refuses_still_runs(test_db, monkeypatch, mock_jar):
    """/voyager/api/me can answer 401 for a live session; the feed reached with li_at counts
    as signed in (linkedin_personal._is_logged_in)."""
    mock_jar(test_db)
    job = _li(test_db)
    asked = _fake_browser(monkeypatch, "https://www.linkedin.com/feed/", 401)
    out = await ll.run_lookup(per_run=20, pause=0, resolve=_no_resolve)
    test_db.refresh(job)
    assert out["stopped"] is None and asked == ["4461186967"]
    assert job.link_kind == "direct"


# ── final review fixes ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_unresolved_short_employer_link_is_not_cached(test_db):
    """Review #1: a short link that does not resolve is an error, not an answer."""
    job = _li(test_db)
    await _run(FakeLinkedIn({"4461186967": {"apply_url": "https://grnh.se/abc", "apply_type": "OffsiteApply"}}),
               resolve=_no_resolve)
    test_db.refresh(job)
    assert test_db.get(LinkedinLookup, "4461186967") is None
    assert job.apply_url is None and job.link_kind == "board"


@pytest.mark.asyncio
async def test_a_deleted_job_is_gone_and_does_not_stop_the_run(test_db):
    """Review #2: LinkedIn answers 404 for a deleted listing; that is an answer, not throttling."""
    for i in range(4):
        _li(test_db, lid=f"446118696{i}", title=f"PM {i}")
    answers = {f"446118696{i}": {"status": 404} for i in range(3)}
    answers["4461186963"] = {"status": 200, "apply_url": GH, "apply_type": "OffsiteApply"}
    fake = FakeLinkedIn(answers)
    out = await _run(fake)
    assert out["stopped"] is None and out["gone"] == 3 and out["employer"] == 1
    assert test_db.get(LinkedinLookup, "4461186960").result == "gone"


@pytest.mark.asyncio
async def test_throttling_still_stops_the_run(test_db):
    for i in range(4):
        _li(test_db, lid=f"446118696{i}", title=f"PM {i}")
    fake = FakeLinkedIn({f"446118696{i}": {"status": 429} for i in range(4)})
    out = await _run(fake)
    assert len(fake.calls) == 3 and out["stopped"] == "no data from LinkedIn 3 times in a row"


@pytest.mark.asyncio
async def test_an_employer_site_without_a_known_system_is_direct(test_db):
    """Review #3: the lookup's link to a company's own site (no known ATS) makes the row direct,
    so it leaves the pending set and the tag agrees with Open."""
    job = _li(test_db)
    await _run(FakeLinkedIn({"4461186967": {"apply_url": "https://cursor.com/careers/gtm", "apply_type": "OffsiteApply"}}))
    test_db.refresh(job)
    assert job.apply_url == "https://cursor.com/careers/gtm" and job.link_kind == "direct"
    assert ll.pending_ids(test_db, 50) == []


def test_ids_with_a_final_answer_leave_the_pending_set(test_db):
    """Review #3: a cached gone/board answer cannot change the row; it must not hold a slot."""
    _li(test_db, lid="4461186960", title="A")
    _li(test_db, lid="4461186961", title="B")
    test_db.add(LinkedinLookup(linkedin_id="4461186960", result="gone"))
    test_db.commit()
    assert ll.pending_ids(test_db, 50) == ["4461186961"]
