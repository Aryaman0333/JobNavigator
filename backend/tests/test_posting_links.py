"""posting_links.py: a new job that repeats a posting the feed has is stored as its duplicate."""
from datetime import datetime, timedelta, timezone

from backend.models.db import Account, Job
from backend.scraper._shared.dedup import make_content_hash, make_external_id


def _job(db, url, company="Twitch", title="Sr. Product Manager, Commerce", source="jobright",
         status="new", apply_url=None, days_old=0, commit=True):
    job = Job(external_id=make_external_id(company, title, url), content_hash=make_content_hash(company, title),
              company=company, title=title, url=url, apply_url=apply_url, source=source, status=status,
              seen=False, saved=status == "saved")
    if days_old:
        job.discovered_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    db.add(job)
    if commit:
        db.commit()
    return job


def test_two_spellings_of_one_greenhouse_posting_are_one_job(test_db):
    first = _job(test_db, "https://job-boards.greenhouse.io/twitch/jobs/8686811002", source="levels_fyi")
    again = _job(test_db, "https://boards.greenhouse.io/embed/job_app?token=8686811002&utm_source=jobright")
    other = _job(test_db, "https://boards.greenhouse.io/embed/job_app?token=8686812002&utm_source=jobright")

    assert first.posting_key == again.posting_key == "greenhouse:8686811002"
    assert again.status == "duplicate" and again.duplicate_of == first.id
    assert first.status == "new" and first.duplicate_of is None
    assert other.status == "new", "a different posting id is a different job"


def test_copies_in_one_flush_link_to_the_first(test_db):
    a = _job(test_db, "https://jobs.citi.com/job/new-york/ach-product-lead/287/96335791200", commit=False)
    b = _job(test_db, "https://jobs.citi.com/job/-/-/287/96335791200?source=APPLICANT_SOURCE-3-354", commit=False)
    test_db.commit()
    assert b.status == "duplicate" and b.duplicate_of == a.id


def test_a_listing_is_a_copy_of_the_employer_posting_with_its_title(test_db):
    """Rule 2: a LinkedIn listing, same company + title as an employer posting from the last 30 days."""
    posting = _job(test_db, "https://jobs.ashbyhq.com/airwallex/1965a683-76f3-430a-9eb5-68456de0f121",
                   company="Airwallex", title="Senior Product Manager", source="jobright")
    listing = _job(test_db, "https://www.linkedin.com/jobs/view/senior-product-manager-at-airwallex-4445868057",
                   company="Airwallex", title="Senior Product Manager", source="levels_fyi")
    assert listing.posting_key == "linkedin:4445868057"
    assert listing.status == "duplicate" and listing.duplicate_of == posting.id


def test_a_listing_is_not_matched_to_an_old_posting_by_title(test_db):
    _job(test_db, "https://jobs.lever.co/acme/1cafb489-9cae-4417-b272-832617484de0",
         company="Acme", title="PM", days_old=45)
    listing = _job(test_db, "https://www.linkedin.com/jobs/view/4461186967", company="Acme", title="PM")
    assert listing.status == "new"


def test_two_employer_postings_with_one_title_stay_two_jobs(test_db):
    """Adobe lists the same title under many requisitions; only the key says they are one."""
    a = _job(test_db, "https://adobe.wd5.myworkdayjobs.com/x/job/San-Jose/Senior-Product-Manager_R171155",
             company="Adobe", title="Senior Product Manager", source="direct")
    b = _job(test_db, "https://adobe.wd5.myworkdayjobs.com/x/job/San-Jose/Senior-Product-Manager_R167610",
             company="Adobe", title="Senior Product Manager", source="direct")
    assert a.status == b.status == "new"


def test_the_employer_posting_takes_over_an_untouched_listing(test_db):
    """Rule 3: the listing came first; when the employer's posting arrives, the listing is the copy."""
    listing = _job(test_db, "https://www.linkedin.com/jobs/view/4461186967", company="Acme", title="PM",
                   source="jobspy_linkedin")
    saved = _job(test_db, "https://www.indeed.com/viewjob?jk=0362e90102d8ac2c", company="Acme", title="PM",
                 source="jobspy_indeed", status="saved")
    posting = _job(test_db, "https://job-boards.greenhouse.io/acme/jobs/4012345", company="Acme", title="PM",
                   source="direct")
    test_db.refresh(listing)
    test_db.refresh(saved)
    assert posting.status == "new"
    assert listing.status == "duplicate" and listing.duplicate_of == posting.id
    assert saved.status == "saved" and saved.duplicate_of is None, "a row the user acted on is never moved"


def test_an_indeed_row_with_an_employer_link_joins_the_company_scrape(test_db):
    posting = _job(test_db, "https://job-boards.greenhouse.io/acme/jobs/4012345", company="Acme", title="PM",
                   source="direct")
    row = _job(test_db, "https://www.indeed.com/viewjob?jk=0362e90102d8ac2c", company="Acme Inc", title="PM",
               source="jobspy_indeed", apply_url="https://boards.greenhouse.io/acme/jobs/4012345?gh_src=x")
    assert row.posting_key == "greenhouse:4012345"
    assert row.duplicate_of == posting.id


def test_a_wrapped_link_gets_its_employer_link_and_key(test_db):
    job = _job(test_db, "https://ad.doubleclick.net/ddm/clk/464361346;269716711;m?"
                        "https://jobs.crateandbarrel.com/job/-/-/351/95352458448?utm_source=linkedin.com",
               company="Crate & Barrel", title="PM", source="linkedin_extension")
    assert job.posting_key == "talentbrew:351:95352458448"
    assert job.apply_url.startswith("https://jobs.crateandbarrel.com/job/-/-/351/95352458448")


def test_the_original_gets_the_employer_link_it_lacked(test_db):
    """The same Indeed listing again, now with the employer's link: it joins the listing, and the
    listing (saved, so it stays) takes the employer's link and key."""
    listing = _job(test_db, "https://www.indeed.com/viewjob?jk=0362e90102d8ac2c", company="Acme", title="PM",
                   source="jobspy_indeed", status="saved")
    again = _job(test_db, "https://www.indeed.com/viewjob?jk=0362E90102D8AC2C&vjs=3", company="Acme", title="PM",
                 source="jobspy_indeed", apply_url="https://jobs.lever.co/acme/1cafb489-9cae-4417-b272-832617484de0")
    test_db.refresh(listing)
    assert again.status == "duplicate" and again.duplicate_of == listing.id
    assert listing.status == "saved"
    assert listing.apply_url == "https://jobs.lever.co/acme/1cafb489-9cae-4417-b272-832617484de0"
    assert listing.posting_key == "lever:1cafb489-9cae-4417-b272-832617484de0"


def test_filtered_rows_are_neither_linked_nor_targets(test_db):
    ignored = _job(test_db, "https://job-boards.greenhouse.io/acme/jobs/4012345", status="ignored")
    visible = _job(test_db, "https://boards.greenhouse.io/acme/jobs/4012345?gh_src=x")
    assert ignored.posting_key == "greenhouse:4012345", "an ignored row is still keyed"
    assert visible.status == "new" and visible.duplicate_of is None


def test_another_accounts_posting_is_never_the_original(test_db):
    from backend.accounts.context import use_account
    _job(test_db, "https://job-boards.greenhouse.io/acme/jobs/4012345")
    partner = Account(name="Partner", role="member")
    test_db.add(partner)
    test_db.commit()
    with use_account(partner.id, test_db):
        theirs = _job(test_db, "https://boards.greenhouse.io/acme/jobs/4012345?gh_src=x")
        assert theirs.account_id == partner.id
        assert theirs.status == "new" and theirs.duplicate_of is None


def test_the_api_lists_where_else_a_posting_was_found(test_db, api_client):
    from backend.models.db import Setting
    test_db.add(Setting(key="dashboard_api_key", value=""))
    test_db.commit()
    first = _job(test_db, "https://job-boards.greenhouse.io/twitch/jobs/8686811002", source="levels_fyi")
    _job(test_db, "https://boards.greenhouse.io/embed/job_app?token=8686811002", source="jobright")

    body = api_client.get(f"/api/jobs/{first.id}").json()
    assert body["posting_key"] == "greenhouse:8686811002"
    assert body["also_on"] == [{"source": "jobright", "url": "https://boards.greenhouse.io/embed/job_app?token=8686811002"}]
    listed = api_client.get("/api/jobs?status=new&limit=50").json()["jobs"]
    assert [j["id"] for j in listed] == [str(first.id)], "the feed hides the duplicate"
    assert listed[0]["also_on"][0]["source"] == "jobright"


def test_saving_another_spelling_from_the_extension_finds_the_posting(test_db, api_client):
    from backend.models.db import Setting
    test_db.add(Setting(key="dashboard_api_key", value=""))
    test_db.commit()
    first = _job(test_db, "https://job-boards.greenhouse.io/acme/jobs/4012345", company="Acme", title="PM")
    out = api_client.post("/api/jobs/save-from-extension", json={
        "title": "Product Manager", "company": "Acme Corp",
        "url": "https://careers.acme.com/open-roles?gh_jid=4012345"}).json()
    assert out["id"] == str(first.id) and out["new"] is False


def test_counts_as_new():
    from backend.scraper._shared.posting_links import counts_as_new
    assert counts_as_new(Job(status="new"))
    assert not counts_as_new(Job(status="duplicate"))


def test_backfill_keys_and_links_untouched_copies(test_db):
    from backend.seed import POSTING_KEYS_MIGRATED_KEY, migrate_posting_keys
    from backend.accounts.context import unscoped
    from backend.accounts.settings import install_row
    from backend.scraper._shared import posting_links

    # rows stored before 3.1: no keys, no linking (the listener is bypassed)
    saved_hook = posting_links.find_original
    posting_links.find_original = lambda *a, **k: None
    posting_links_listing = posting_links.listing_copies
    posting_links.listing_copies = lambda *a, **k: []
    try:
        old = _job(test_db, "https://job-boards.greenhouse.io/twitch/jobs/8686811002", days_old=5)
        applied = _job(test_db, "https://boards.greenhouse.io/embed/job_app?token=8686811002", status="applied")
        copy = _job(test_db, "https://job-boards.greenhouse.io/embed/job_app?for=twitch&token=8686811002")
    finally:
        posting_links.find_original = saved_hook
        posting_links.listing_copies = posting_links_listing
    for j in (old, applied, copy):
        j.posting_key = None
    test_db.commit()

    with unscoped():
        out = migrate_posting_keys(test_db)
        assert install_row(test_db, POSTING_KEYS_MIGRATED_KEY) is not None
        assert migrate_posting_keys(test_db) == {}, "runs once"
    assert out == {"keyed": 3, "linked": 2}
    for j in (old, applied, copy):
        test_db.refresh(j)
    assert applied.status == "applied" and applied.duplicate_of is None, "the applied row keeps the posting"
    assert old.status == "duplicate" and old.duplicate_of == applied.id
    assert copy.status == "duplicate" and copy.duplicate_of == applied.id
