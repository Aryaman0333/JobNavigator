"""telemetry/umami.py: what goes to Umami, and that nothing goes when it must not."""
import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from backend.models.db import Company, ScrapeLog
from backend.telemetry import umami as U
from backend.tests.r4_support import client, set_setting  # noqa: F401 (fixture)


@pytest.fixture
def sent(monkeypatch, test_db):
    """Captured request bodies; a website id and the test database for the sender."""
    calls = []

    def handler(request):
        import json
        calls.append((request.headers.get("user-agent"), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(U, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(U, "UMAMI_WEBSITE_ID", "site-123")
    monkeypatch.setattr(U, "_session", sessionmaker(bind=test_db.get_bind()))
    monkeypatch.delenv("JN_TELEMETRY", raising=False)
    return calls


@pytest.mark.asyncio
async def test_payload_shape(sent):
    assert await U.send([("scraper_health", {"kind": "workday", "runs": 2})]) == 1
    agent, body = sent[0]
    assert body == {"type": "event", "payload": {"website": "site-123", "hostname": "jobnavigator", "url": "/server",
                                                 "name": "scraper_health", "data": {"kind": "workday", "runs": 2},
                                                 "language": "en"}}
    assert agent.startswith("Mozilla/5.0") and "JobNavigator/" in agent


@pytest.mark.asyncio
async def test_nothing_sent_when_not_asked(sent):
    assert await U.send_start() == 0 and await U.send_daily() == 0 and sent == []


@pytest.mark.asyncio
async def test_nothing_sent_when_env_is_off(sent, test_db, monkeypatch):
    set_setting(test_db, "telemetry_level", "full")
    monkeypatch.setenv("JN_TELEMETRY", "off")
    assert await U.send_start() == 0 and await U.send_daily() == 0 and sent == []


@pytest.mark.asyncio
async def test_nothing_sent_without_a_website_id(sent, test_db, monkeypatch):
    set_setting(test_db, "telemetry_level", "full")
    monkeypatch.setattr(U, "UMAMI_WEBSITE_ID", "")
    assert await U.send_start() == 0 and await U.send_daily() == 0 and sent == []


@pytest.mark.asyncio
async def test_app_started_on_each_start(sent, test_db):
    set_setting(test_db, "telemetry_level", "essentials")
    await U.send_start()
    await U.send_start()
    assert [b["payload"]["name"] for _a, b in sent] == ["app_started", "app_started"]


@pytest.mark.asyncio
async def test_a_broken_database_does_not_escape_the_start_send(sent, test_db, monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(U, "_session", broken)
    assert await U.send_start() == 0


# ── browser events, relayed ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_relay_forwards_only_at_full(sent, test_db, client):
    set_setting(test_db, "telemetry_level", "essentials")
    assert client.post("/api/telemetry/event", json={"name": "job_saved", "data": {}, "url": "/feed"}).json() == {"sent": False}
    set_setting(test_db, "telemetry_level", "full")
    assert client.post("/api/telemetry/event", json={"name": "job_opened", "data": {"link_kind": "direct"},
                                                     "url": "/feed"}).json() == {"sent": True}
    payload = sent[-1][1]["payload"]
    assert payload["hostname"] == "jobnavigator" and payload["url"] == "/feed" and payload["name"] == "job_opened"
    assert payload["data"]["link_kind"] == "direct" and len(payload["data"]["install_id"]) == 36


@pytest.mark.asyncio
async def test_relay_page_view_is_an_umami_page_view(sent, test_db, client):
    set_setting(test_db, "telemetry_level", "full")
    client.post("/api/telemetry/event", json={"name": "page_view", "data": {}, "url": "/resumes/:id"})
    payload = sent[-1][1]["payload"]
    assert payload["url"] == "/resumes/:id" and "name" not in payload


def test_relay_drops_text_paths_and_odd_values():
    name, data, url = U.clean_browser_event(
        "job_opened", {"link_kind": "direct", "title": "Senior PM at Zyxcorp", "n": 3, "ok": True,
                       "BadKey": "x", "nested": {"a": 1}}, "/resumes/Zyxcorp Resume?x=1")
    assert data == {"link_kind": "direct", "n": 3, "ok": True} and url == "/"
    assert U.clean_browser_event("Job Opened!", {}, "/feed") is None
    assert U.clean_browser_event("job_opened", "not a dict", "/feed")[1] == {}


@pytest.mark.asyncio
async def test_relay_is_rate_limited(sent, test_db, monkeypatch):
    set_setting(test_db, "telemetry_level", "full")
    monkeypatch.setattr(U, "RELAY_PER_MINUTE", 3)
    monkeypatch.setattr(U, "_relayed", [])
    results = [await U.relay("job_saved", {}, "/feed") for _ in range(5)]
    assert results == [True, True, True, False, False]


@pytest.mark.asyncio
async def test_daily_send_stamps_last_sent(sent, test_db):
    from backend.accounts.settings import get_install_setting
    set_setting(test_db, "telemetry_level", "essentials")
    assert await U.send_daily() >= 1
    test_db.expire_all()
    assert get_install_setting(test_db, "telemetry_last_sent_at")


@pytest.mark.asyncio
async def test_essentials_sends_no_failing_hosts(sent, test_db):
    set_setting(test_db, "telemetry_level", "essentials")
    c = Company(name="Acme", scrape_urls=["https://job-boards.greenhouse.io/acme"], active=True)
    test_db.add(c)
    test_db.commit()
    test_db.add(ScrapeLog(company_id=c.id, source="playwright_Acme", error="BoardNotFoundError (HTTP 404)"))
    test_db.commit()
    await U.send_daily()
    health = [b["payload"]["data"] for _a, b in sent if b["payload"]["name"] == "scraper_health"]
    assert health and all("failing_hosts" not in d for d in health)


@pytest.mark.asyncio
async def test_umami_down_is_logged_not_raised(monkeypatch, test_db, caplog):
    def down(request):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(U, "_transport", httpx.MockTransport(down))
    monkeypatch.setattr(U, "UMAMI_WEBSITE_ID", "site-123")
    assert await U.send([("app_started", {})]) == 0
    assert any("Telemetry not sent" in r.message for r in caplog.records)
