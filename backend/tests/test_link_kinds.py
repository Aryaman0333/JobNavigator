"""link_kinds.py: whether a job's link reaches the employer's own site (direct-links plan)."""
import pytest

from backend.models.db import Job
from backend.scraper._shared.link_kinds import classify, link_kind


def test_an_employer_posting_is_direct():
    assert link_kind("https://job-boards.greenhouse.io/x/jobs/1234567", None) == "direct"


def test_a_company_site_without_a_known_system_is_direct():
    assert link_kind("https://cursor.com/careers/gtm-systems", None) == "direct"


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/jobs/view/4461186967",
    "https://www.indeed.com/viewjob?jk=0362e90102d8ac2c",
    "https://www.glassdoor.com/job-listing/x",
    "https://www.ziprecruiter.com/kn/AAJVrD7cHvDc1iynP",
    "https://de-ch.whatjobs.com/pub_api__cpl__1__7095",
    "https://t.me/huntmejob/38746",
    "https://www.levels.fyi/jobs?jobId=2ci7r6weraiqb",
    "https://jobright.ai/jobs/info/abc",
    "https://www.hackajob.com/job/x",
    "https://haystack.cv/jobs/x",
    "https://app.swooped.co/job-postings/x",
])
def test_board_listings_are_board(url):
    assert link_kind(url, None) == "board"


def test_a_board_row_with_an_employer_link_is_direct():
    assert link_kind("https://www.indeed.com/viewjob?jk=0362e90102d8ac2c",
                     "https://boards.greenhouse.io/acme/jobs/4012345") == "direct"


@pytest.mark.parametrize("url", ["https://grnh.se/zvej33q44us", "https://dsp.prng.co/w-ox7b",
                                 "https://click.appcast.io/t/x"])
def test_short_links_to_the_employer_are_direct(url):
    assert link_kind(url, None) == "direct"


def test_no_link_is_board():
    assert link_kind(None, None) == "board"


def test_classify_keeps_easy_apply():
    job = Job(url="https://www.linkedin.com/jobs/view/4461186967", link_kind="easy_apply")
    classify(job)
    assert job.link_kind == "easy_apply"
    job.apply_url = "https://boards.greenhouse.io/acme/jobs/4012345"
    classify(job)
    assert job.link_kind == "direct"
