"""Jobright stores its own AI summary of a job; employer_descriptions swaps in the employer's
text from the job's own link, and keeps the summary when that fetch gives nothing."""
import asyncio

from backend.scraper._shared import employer_text

LONG = "Build payment systems for advisors. " * 20


def _run(jobs, landed, pages, monkeypatch):
    calls = []

    async def fake_fetch(url, job=None):
        calls.append(url)
        return pages.get(url)

    monkeypatch.setattr("backend.scraper.ats._descriptions._fetch_job_description", fake_fetch)
    n = asyncio.run(employer_text.employer_descriptions(jobs, landed))
    return n, calls


def test_employer_text_replaces_the_summary(monkeypatch):
    jobs = [{"url": "https://job-boards.greenhouse.io/altruist/jobs/6217332004", "description": "AI summary"}]
    n, calls = _run(jobs, {}, {jobs[0]["url"]: LONG}, monkeypatch)
    assert n == 1
    assert jobs[0]["description"] == LONG


def test_the_landed_employer_link_is_fetched(monkeypatch):
    jobs = [{"url": "https://lnkd.in/abc", "description": "AI summary"}]
    landed = {"https://lnkd.in/abc": "https://jobs.lever.co/acme/123"}
    n, calls = _run(jobs, landed, {"https://jobs.lever.co/acme/123": LONG}, monkeypatch)
    assert calls == ["https://jobs.lever.co/acme/123"]
    assert jobs[0]["description"] == LONG


def test_summary_kept_when_the_fetch_fails_or_is_short(monkeypatch):
    jobs = [{"url": "https://acme.com/careers/1", "description": "AI summary"},
            {"url": "https://acme.com/careers/2", "description": "AI summary 2"}]
    n, _ = _run(jobs, {}, {"https://acme.com/careers/2": "Apply now"}, monkeypatch)
    assert n == 0
    assert [j["description"] for j in jobs] == ["AI summary", "AI summary 2"]


def test_board_links_are_not_fetched(monkeypatch):
    jobs = [{"url": "https://jobright.ai/jobs/info/abc", "description": "AI summary"}]
    n, calls = _run(jobs, {}, {}, monkeypatch)
    assert calls == [] and n == 0


def test_a_fetch_error_keeps_the_summary(monkeypatch):
    async def boom(url, job=None):
        raise RuntimeError("timeout")

    monkeypatch.setattr("backend.scraper.ats._descriptions._fetch_job_description", boom)
    jobs = [{"url": "https://acme.com/careers/1", "description": "AI summary"}]
    assert asyncio.run(employer_text.employer_descriptions(jobs, {})) == 0
    assert jobs[0]["description"] == "AI summary"
