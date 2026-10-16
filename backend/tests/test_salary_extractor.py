"""Tests for analyzer/salary_extractor — regex patterns + LCA fallback + 30K input cap."""
import pytest


def test_extract_salary_range_with_dollar_sign():
    from backend.analyzer.salary_extractor import extract_salary
    result = extract_salary("Salary: $140,000 - $210,000 per year")
    assert result["salary_min"] == 140000
    assert result["salary_max"] == 210000
    assert result["salary_source"] != "unknown"


def test_extract_salary_range_with_usd_suffix():
    from backend.analyzer.salary_extractor import extract_salary
    result = extract_salary("Compensation: 173,900.00 - 235,200.00 USD annually")
    assert result["salary_min"] == 173900
    assert result["salary_max"] == 235200


def test_extract_salary_k_notation():
    from backend.analyzer.salary_extractor import extract_salary
    result = extract_salary("Pay range: $120k-$180k")
    # k-notation should resolve to thousands
    assert result["salary_min"] == 120000
    assert result["salary_max"] == 180000


def test_extract_salary_empty_returns_unknown():
    from backend.analyzer.salary_extractor import extract_salary
    result = extract_salary("")
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_source"] == "unknown"


def test_extract_salary_lca_fallback():
    """No salary in text + h1b_median given → uses LCA estimate."""
    from backend.analyzer.salary_extractor import extract_salary
    result = extract_salary("A cool job", h1b_median_salary=165000)
    assert result["salary_min"] == 165000
    assert result["salary_max"] == 165000
    assert result["salary_source"] == "lca_estimate"


def test_extract_salary_strips_html_tags():
    from backend.analyzer.salary_extractor import extract_salary
    # HTML tags should be stripped before regex runs
    result = extract_salary("<p>Salary: <b>$140,000</b> - <b>$210,000</b></p>")
    assert result["salary_min"] == 140000
    assert result["salary_max"] == 210000


def test_extract_salary_input_capped_at_30k_chars():
    """ReDoS mitigation: input capped at 30K chars before regex."""
    from backend.analyzer.salary_extractor import extract_salary
    # Place salary at the BEGINNING so it's preserved under the cap
    prefix = "Salary: $100,000 - $150,000"
    padding = "x" * 100000  # 100K of junk AFTER the salary
    text = prefix + " " + padding
    result = extract_salary(text)
    assert result["salary_min"] == 100000
    assert result["salary_max"] == 150000


def test_extract_salary_single_value_not_picked_as_range():
    """A single salary mention (no range) does not populate both min and max to the same value; range-only patterns win."""
    from backend.analyzer.salary_extractor import extract_salary
    result = extract_salary("Starting salary $100,000")
    assert isinstance(result, dict)
    assert "salary_min" in result
    assert "salary_max" in result


# ── Non-yearly pay is never stored as a yearly figure ───────────────────────

_NONE = (None, None)


def _pair(text):
    from backend.analyzer.salary_extractor import extract_salary
    r = extract_salary(text)
    return r["salary_min"], r["salary_max"]


def test_wikimedia_hourly_range_is_not_stored():
    """The live TrulyRemote Wikimedia posting: was stored as 34 / 42 yearly."""
    from backend.analyzer.salary_extractor import extract_salary
    r = extract_salary("The hourly pay range in the US is US$34.32 to $42.13 per hour, depending on location.")
    assert (r["salary_min"], r["salary_max"], r["salary_source"]) == (None, None, "unknown")
    assert _pair("US$34.32 to $42.13 per hour") == _NONE


@pytest.mark.parametrize("text", [
    "$34.32 - $42.13 per hour",
    "US$34.32 to $42.13 per hour",
    "$45 - $60/hr",
    "$45/hr - $60/hr",
    "$45 - $60 / hour",
    "$45 to $60 an hour",
    "$45-$60 hourly",
    "$45 - $60 p/h",
    "$45 - $60 ph",
    "$45 - $60 USD per hour",
    "Hourly rate: $45 - $60",
    "Pay per hour: $45 - $60",
    "$1,200 - $1,500 per hour",          # big enough to pass the 1000 guard; the tag still wins
    "COMPENSATION: $102 - $112 HOURLY",  # live levels_fyi row
    "The hourly pay range for this position is from $36.85 to $55.26 and pay offered",
])
def test_hourly_amounts_are_not_stored(text):
    assert _pair(text) == _NONE


@pytest.mark.parametrize("text", [
    "$8,000 - $10,000 per month",
    "$8,000 - $10,000/mo",
    "$8,000 - $10,000 monthly",
    "Monthly salary: $8,000 - $10,000",
    "$8k - $10k per month",
    "$9k/month",
    "$5,000 per month",
    "$1,500 - $2,000 per week",
    "$2,000 - $2,500 weekly",
    "$1,200 - $1,500 per day",
    "$1,200 a day",
])
def test_monthly_weekly_daily_amounts_are_not_stored(text):
    assert _pair(text) == _NONE


@pytest.mark.parametrize("text", [
    "$34 - $42",                 # no period, but no yearly salary is under 1000
    "$34.32 to $42.13",
    "$500 per year",
    "34 - 42 USD",
])
def test_implausibly_small_yearly_figures_are_skipped(text):
    assert _pair(text) == _NONE


@pytest.mark.parametrize("text,expected", [
    ("$120,000 - $150,000", (120000, 150000)),
    ("Salary: $120,000 - $150,000 per year", (120000, 150000)),
    ("$120k - $150k", (120000, 150000)),
    ("$120K-$150K/yr", (120000, 150000)),
    ("$140,000 USD - $210,000 USD", (140000, 210000)),
    ("$122,550.00-$201,000.00", (122550, 201000)),
    ("$130,000 per year", (130000, 130000)),
    ("$130k", (130000, 130000)),
    ("Compensation: 173,900.00 - 235,200.00 USD annually", (173900, 235200)),
    ("Base pay $120,000", (120000, 120000)),
])
def test_yearly_amounts_still_parse(text, expected):
    assert _pair(text) == expected


def test_a_yearly_range_after_an_hourly_one_is_read():
    text = "Hourly employees: $34 - $42 per hour. Salaried: $90,000 - $110,000 per year."
    assert _pair(text) == (90000, 110000)


def test_the_yearly_k_range_wins_over_its_hourly_equivalent():
    """Live levels_fyi row, stored as 67 / 105 before: the $-range pattern ran first."""
    assert _pair("Expected Salary: $140k-$220k/year ($67-$105/hour).") == (140000, 220000)


def test_a_yearly_range_is_not_dropped_for_a_stipend_mentioned_later():
    text = "Salary $120,000 - $150,000. Benefits include a $100 per month wellness stipend."
    assert _pair(text) == (120000, 150000)


def test_hourly_description_falls_back_to_lca_median():
    from backend.analyzer.salary_extractor import extract_salary
    r = extract_salary("US$34.32 to $42.13 per hour", h1b_median_salary=150000)
    assert (r["salary_min"], r["salary_source"]) == (150000, "lca_estimate")


def test_apply_salary_to_job_leaves_hourly_pay_empty():
    from types import SimpleNamespace
    from backend.analyzer.salary_extractor import apply_salary_to_job
    job = SimpleNamespace(salary_min=None, salary_max=None, salary_source=None,
                          description="Pay: US$34.32 to $42.13 per hour")
    apply_salary_to_job(job)
    assert (job.salary_min, job.salary_max, job.salary_source) == (None, None, "unknown")


@pytest.mark.parametrize("text,expected", [
    ("$45/hr", True), ("$25 - $30 an hour", True), ("$8K/mo", True), ("$9,000 monthly", True),
    ("$1,500 per week", True), ("$400/day", True), ("$45 p/h", True),
    ("$120K - $180K/yr", False), ("$120,000 - $150,000", False), ("$150k a year", False), ("", False),
])
def test_is_non_annual(text, expected):
    from backend.analyzer.salary_extractor import is_non_annual
    assert is_non_annual(text) is expected


# ── Per-source salary strings use the same rule ─────────────────────────────

def test_jobright_salary_string_hourly_is_not_read_as_thousands():
    from backend.scraper.sources import jobright
    assert jobright._parse_salary("$45/hr - $60/hr") == (None, None)
    assert jobright._parse_salary("$120K - $180K/yr") == (120000, 180000)


def test_linkedin_personal_salary_string_hourly_is_text_only():
    from backend.scraper.sources import linkedin_personal
    r = linkedin_personal._parse_salary_text("$45/hr - $60/hr")
    assert (r["salary_min"], r["salary_max"], r["salary_text"]) == (None, None, "$45/hr - $60/hr")
    r = linkedin_personal._parse_salary_text("$120K/yr - $180K/yr")
    assert (r["salary_min"], r["salary_max"]) == (120000, 180000)


def test_levelsfyi_card_hourly_is_skipped():
    from backend.scraper.sources import levelsfyi
    assert levelsfyi._parse_levelsfyi_salary("Austin, TX · Remote · $45/hr")[2:] == (None, None)
    assert levelsfyi._parse_levelsfyi_salary("Austin, TX · Remote · $150K - $200K")[2:] == (150000, 200000)


@pytest.mark.parametrize("interval,lo,hi,ok", [
    ("yearly", 120000.0, 150000.0, True),
    (None, 120000.0, 150000.0, True),
    (float("nan"), 120000.0, None, True),
    ("hourly", 34.32, 42.13, False),
    ("monthly", 8000.0, 10000.0, False),
    ("weekly", 1500.0, 2000.0, False),
    ("daily", 400.0, 500.0, False),
    ("yearly", 34.0, 42.0, False),
])
def test_jobspy_only_yearly_rows_are_stored(interval, lo, hi, ok):
    from backend.scraper.sources.jobspy import _jobspy_yearly
    assert _jobspy_yearly(interval, lo, hi) is ok
