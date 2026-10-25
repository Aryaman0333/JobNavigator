"""The employer's own description for jobs a board only summarises.

Jobright stores its own AI summary of a job, so two copies of one role (another city, a
repost) never read word for word alike and `same_role.py` cannot prove them. When the job's
link is the employer's (not a board), fetch the description there and keep it instead; the
board's summary stays when the fetch fails or gives too little text.
"""
import asyncio
import logging

from backend.scraper._shared.link_kinds import BOARD, link_kind

logger = logging.getLogger("jobnavigator.employer_text")

MIN_CHARS = 200   # a fetch shorter than this is a shell or an error page, not a description


async def employer_descriptions(jobs: list[dict], landed: dict | None = None,
                                max_concurrent: int = 5) -> int:
    """Replace each job dict's `description` with the employer's text in place. `landed` maps a
    short link to where it lands (resolve_short_links). Returns how many were replaced."""
    from backend.scraper.ats import _descriptions

    landed = landed or {}
    sem = asyncio.Semaphore(max_concurrent)

    async def one(j: dict) -> bool:
        link = landed.get(j.get("url")) or j.get("url")
        if not link or link_kind(link, None) == BOARD:
            return False
        async with sem:
            try:
                text = await _descriptions._fetch_job_description(link, job=j)
            except Exception as e:  # noqa: BLE001 - the summary stays
                logger.info(f"employer text: {link}: {e}")
                return False
        if not text or len(text.strip()) < MIN_CHARS:
            return False
        j["description"] = text
        return True

    done = await asyncio.gather(*(one(j) for j in jobs))
    return sum(done)
