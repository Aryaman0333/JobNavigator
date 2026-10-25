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


def _mock_on(db):
    db.add(Setting(key="linkedin_use_mock_account", value="true"))
    db.commit()


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
    assert job.status == "duplicate" and job.duplicate_of == posting.id


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
async def test_lookup_without_a_session_does_nothing(test_db, monkeypatch):
    _mock_on(test_db)
    job = _li(test_db)
    from backend.scraper.sources import linkedin_extension as le
    monkeypatch.setattr(le, "_load_session_cookies", lambda: None)
    out = await ll.run_lookup(per_run=20, pause=0)
    test_db.refresh(job)
    assert out["stopped"] == "no LinkedIn mock session"
    assert job.link_kind == "board"


@pytest.mark.asyncio
async def test_lookup_refuses_the_personal_account(test_db, monkeypatch):
    test_db.add(Setting(key="linkedin_use_mock_account", value="false"))
    test_db.commit()
    _li(test_db)
    from backend.scraper.sources import linkedin_extension as le
    monkeypatch.setattr(le, "_load_session_cookies", lambda: [{"name": "li_at", "value": "x"}])
    out = await ll.run_lookup(per_run=20, pause=0)
    assert out["stopped"] == "the LinkedIn session is not the mock account"


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


def test_settings_default_to_an_hourly_run_of_twenty():
    from backend.seed import DEFAULT_SETTINGS
    from backend.accounts.settings import SETTING_SECTIONS, KEY_SECTION
    assert DEFAULT_SETTINGS["linkedin_lookup_cron"][0] == "20 * * * *"
    assert DEFAULT_SETTINGS["linkedin_lookup_per_run"][0] == "20"
    section = SETTING_SECTIONS[KEY_SECTION["linkedin_lookup_cron"]]
    assert section["scope"] == "owner_only" and KEY_SECTION["linkedin_lookup_per_run"] == section["id"]


@pytest.mark.parametrize("cron, scheduled", [("20 * * * *", True), ("", False)])
def test_the_scheduler_runs_the_lookup_on_its_cron(test_db, monkeypatch, cron, scheduled):
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
    test_db.add(Setting(key="linkedin_lookup_cron", value=cron))
    test_db.commit()
    sched_mod.configure_scheduler()
    assert ("linkedin_lookup" in rec.ids) is scheduled


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
    assert short.status == "duplicate" and short.duplicate_of == posting.id


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
