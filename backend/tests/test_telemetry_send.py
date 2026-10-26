"""telemetry/umami.py: what goes to Umami, and that nothing goes when it must not."""
import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from backend.models.db import Company, ScrapeLog
from backend.telemetry import umami as U
from backend.tests.r4_support import set_setting


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
async def test_first_start_then_app_started(sent, test_db):
    set_setting(test_db, "telemetry_level", "essentials")
    await U.send_start()
    await U.send_start()
    names = [b["payload"]["name"] for _a, b in sent]
    assert names == ["install_first_start", "app_started", "app_started"]


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
