"""Salary extraction from JD text + H-1B LCA median fallback.

Only yearly figures are stored. An amount tagged hourly, daily, weekly or monthly is skipped,
never annualised (the convention every source follows: freehire's `_annual_salary`, apify's
`_annual_from_text`, CaribbeanJobs' and TrulyRemote's USD-annual gates), so the posted text in
the description is what shows it. A "yearly" figure under 1000 without a "k" is not a salary.
"""
import re
import logging

logger = logging.getLogger("jobnavigator.salary")

# Below this, a figure with no "k" is not a yearly salary ("$34.32 to $42.13" is hourly pay).
_MIN_YEARLY = 1000

# A period tag right after an amount: "/hr", "per hour", "an hour", "hourly", "p/h", "ph",
# "a day", "/wk", "per month", "pcm", … An optional currency code or "(USD)" may come first.
_PERIOD_WORDS = (
    r"(?:per|an?|each|every|/)\s*(?:hour|hr)s?\b|hourly\b|p\s*/\s*h\b|p\.\s*h\.|ph\b|/\s*h\b"
    r"|(?:per|an?|each|every|/)\s*day\b|daily\b|p\s*/\s*d\b|/\s*d\b"
    r"|(?:per|an?|each|every|/)\s*(?:week|wk)s?\b|weekly\b|p\s*/\s*w\b|pw\b|/\s*w\b"
    r"|(?:per|an?|each|every|/)\s*(?:month|mo|mth)s?\b|monthly\b|p\s*/\s*m\b|pcm\b|/\s*m\b"
)
_PERIOD_AFTER_RE = re.compile(
    r"\s*(?:\(?\s*(?:USD|US\s?\$|dollars?)\s*\)?)?\s*\(?\s*(?:" + _PERIOD_WORDS + r")",
    re.IGNORECASE,
)
# A period named just before the amount in the same clause: "Hourly pay range: $34 - $42",
# "Monthly salary: $8,000". The clause stops at a sentence break, a comma or an earlier
# number, so "Hourly: $34 - $42 or $70,000 - $87,000" still reads the yearly pair.
_PERIOD_BEFORE_RE = re.compile(
    r"\b(?:hourly|daily|weekly|monthly|day\s+rate)\b|\b(?:per|an?)\s+(?:hour|hr|day|week|month)\b",
    re.IGNORECASE,
)
_CLAUSE_BREAK_RE = re.compile(r"[.;!?|,](?:\s|$)|\n|\d")
# For a whole salary string from a source's own field ("$45/hr", "$8K/mo", "$25 - $30 an hour").
_NON_ANNUAL_TEXT_RE = re.compile(
    r"\b(?:hourly|daily|weekly|monthly|pcm)\b|\b(?:per|an?|each|every)\s+(?:hour|hr|day|week|wk|month|mo|mth)s?\b"
    r"|/\s*(?:hour|hr|h|day|d|week|wk|w|month|mo|mth|m)s?\b|\bp\s*/\s*[hdwm]\b|\bp\.\s*h\.|\b(?:ph|pw)\b",
    re.IGNORECASE,
)


def is_non_annual(text: str) -> bool:
    """True when a salary string names a period shorter than a year (hour, day, week, month)."""
    return bool(text and _NON_ANNUAL_TEXT_RE.search(text))


def _tagged_non_annual(text: str, start: int, end: int) -> bool:
    """True when the amount at text[start:end] is tagged hourly/daily/weekly/monthly, right after
    it or earlier in the same clause."""
    if _PERIOD_AFTER_RE.match(text, end):
        return True
    before = text[max(0, start - 60):start]
    breaks = list(_CLAUSE_BREAK_RE.finditer(before))
    if breaks:
        before = before[breaks[-1].end():]
    return bool(_PERIOD_BEFORE_RE.search(before))


def _to_int(amount: str) -> int:
    return int(amount.replace(",", ""))


# Each pattern yields (low, high) from a match; k-notation multiplies by 1000.
_PATTERNS = (
    # 1: $XXX,XXX - $XXX,XXX, e.g. $140,000 USD - $210,000 USD, USD$150,000 - USD$200,000,
    #    $122,550.00-$201,000.00. Cents are matched and dropped.
    (re.compile(
        r'(?:USD\s*)?\$\s*(\d{1,3}(?:,\d{3})*)(?:\.\d{1,2})?\s*(?:USD|per\s*year|annually|/\s*yr|/\s*year|a\s*year)?\s*(?:[-–—/]+|(?:and\s+)?up\s+to|to|and)\s*(?:USD\s*)?\$?\s*(\d{1,3}(?:,\d{3})*)(?:\.\d{1,2})?'
    ), lambda m: (_to_int(m.group(1)), _to_int(m.group(2)))),
    # 1b: bare numbers with USD: 173,900.00 - 235,200.00 USD
    (re.compile(
        r'(\d{1,3}(?:,\d{3})*)(?:\.\d{1,2})?\s*(?:USD\s*)?(?:[-–—/]+|(?:and\s+)?up\s+to|to)\s*(\d{1,3}(?:,\d{3})*)(?:\.\d{1,2})?\s*USD'
    ), lambda m: (_to_int(m.group(1)), _to_int(m.group(2)))),
    # 2: $XXXk - $XXXk
    (re.compile(
        r'\$\s*(\d{2,3})\s*[kK]\s*(?:[-–—/]+|(?:and\s+)?up\s+to|to)\s*\$\s*(\d{2,3})\s*[kK]'
    ), lambda m: (int(m.group(1)) * 1000, int(m.group(2)) * 1000)),
    # 3: $XXX,XXX per year / annually (single amount)
    (re.compile(
        r'\$\s*(\d{1,3}(?:,\d{3})*)(?:\.\d{1,2})?\s*(?:per\s*year|annually|/\s*yr|/\s*year|a\s*year)',
        re.IGNORECASE,
    ), lambda m: (_to_int(m.group(1)),) * 2),
    # 4: $XXXk (single)
    (re.compile(r'\$\s*(\d{2,3})\s*[kK]'), lambda m: (int(m.group(1)) * 1000,) * 2),
    # 5: a single bare $XXX,XXX of at least 30,000
    (re.compile(r'\$\s*(\d{3},\d{3})(?:\.\d{1,2})?'),
     lambda m: (_to_int(m.group(1)),) * 2 if _to_int(m.group(1)) >= 30000 else None),
)


def _find_yearly(description: str):
    """(low, high) of the first yearly salary in the text, skipping amounts tagged with a shorter
    period and implausibly small figures."""
    for pattern, values in _PATTERNS:
        for match in pattern.finditer(description):
            found = values(match)
            if not found:
                continue
            low, high = found
            if min(low, high) < _MIN_YEARLY:
                continue
            if _tagged_non_annual(description, match.start(), match.end()):
                continue
            return low, high
    return None


def extract_salary(description: str, h1b_median_salary: int = None) -> dict:
    """Extract salary range from job description text, falling back to H-1B LCA median if none found."""
    if not description:
        if h1b_median_salary:
            return {
                "salary_min": h1b_median_salary,
                "salary_max": h1b_median_salary,
                "salary_source": "lca_estimate",
            }
        return {"salary_min": None, "salary_max": None, "salary_source": "unknown"}

    # Cap input size before any regex runs (matches the scraper's 30K truncation) to bound the
    # HTML stripper + salary regex against pathological input.
    description = description[:30_000]

    if "<" in description and ">" in description:
        import html as _html
        description = _html.unescape(re.sub(r'<[^>]+>', ' ', description))

    found = _find_yearly(description)
    if found:
        return {"salary_min": found[0], "salary_max": found[1], "salary_source": "posting"}

    # Fallback to LCA median
    if h1b_median_salary:
        return {
            "salary_min": h1b_median_salary,
            "salary_max": h1b_median_salary,
            "salary_source": "lca_estimate",
        }

    return {"salary_min": None, "salary_max": None, "salary_source": "unknown"}


def apply_salary_to_job(job, company_h1b_median: int = None) -> None:
    """Extract salary from job description and update job fields; only updates if no salary is already set from the scraper."""
    if job.salary_min and job.salary_source == "posting":
        return  # Already have salary from scraper

    result = extract_salary(job.description or "", company_h1b_median)
    job.salary_min = result["salary_min"]
    job.salary_max = result["salary_max"]
    job.salary_source = result["salary_source"]
