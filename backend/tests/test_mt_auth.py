"""MT-10 · Install password -> account -> PIN; the per-browser `jn_account` cookie.

`client` (r4_support) sends the install key as X-API-Key and, by default, X-Account for
the owner; the browser-path tests drop X-Account and go through POST /api/auth/switch.
"""
import base64
import json
import time
import uuid

import pytest

from backend.accounts import auth as A
from backend.accounts.context import use_account
from backend.models.db import Account, Job, Setting
from backend.tests.r4_support import API_KEY, client  # noqa: F401 (fixture)


@pytest.fixture
def owner(test_db):
    return test_db.query(Account).filter(Account.role == "owner").one()


def _member(db, name="Partner", pin=None):
    m = Account(name=name, role="member", color="#2e9e6b",
                pin_hash=A.hash_pin(pin) if pin else None)
    db.add(m)
    db.commit()
    return m


def _set_pin(db, acc, pin):
    acc.pin_hash = A.hash_pin(pin) if pin else None
    db.commit()


@pytest.fixture
def browser(client):
    """The browser path: install key, no X-Account header."""
    client.headers.pop("X-Account", None)
    client.cookies.clear()
    return client


def _switch(c, account_id, pin=None):
    body = {"account_id": str(account_id)}
    if pin is not None:
        body["pin"] = pin
    return c.post("/api/auth/switch", json=body)


def _me(c):
    return c.get("/api/auth/me")


def _job(db, account_id, title):
    with use_account(account_id):
        db.add(Job(external_id=f"ext-{title}", content_hash=f"h-{title}", company="Co",
                   title=title, url=f"https://x.example/{title}", source="test", status="new"))
        db.commit()


# ── PIN hashing ──────────────────────────────────────────────────────────────

def test_pin_hash_is_salted_scrypt_and_verifies():
    h1, h2 = A.hash_pin("1234"), A.hash_pin("1234")
    assert h1.startswith("scrypt$") and h1 != h2           # per-hash salt
    assert "1234" not in h1
    assert A.verify_pin("1234", h1) and A.verify_pin("1234", h2)
    assert not A.verify_pin("1235", h1)
    assert not A.verify_pin("1234", None)
    assert not A.verify_pin("12345", h1) and not A.verify_pin("12a4", h1)
    with pytest.raises(ValueError):
        A.hash_pin("123")


# ── one account: no picker ───────────────────────────────────────────────────

def test_single_account_acts_as_owner_without_cookie(browser, test_db, owner):
    _job(test_db, owner.id, "mine")
    r = _me(browser)
    assert r.status_code == 200, r.text
    assert r.json()["account"] == {"id": str(owner.id), "name": owner.name, "color": owner.color,
                                   "role": "owner", "has_pin": False}
    assert r.json()["accounts_count"] == 1
    assert browser.get("/api/jobs").status_code == 200
    assert "jn_account" not in browser.cookies


def test_single_account_ignores_a_bad_cookie(browser, owner):
    browser.cookies.set("jn_account", "garbage.value")
    assert _me(browser).json()["account"]["id"] == str(owner.id)


def test_jn_session_cookie_alone_still_works_with_one_account(client, owner):
    client.headers.pop("X-Account", None)
    client.headers.pop("X-API-Key", None)
    assert client.get("/api/jobs").status_code == 401                 # no key at all
    client.cookies.set("jn_session", API_KEY)
    assert client.get("/api/jobs").status_code == 200
    assert _me(client).json()["account"]["id"] == str(owner.id)


# ── two accounts: selection required ─────────────────────────────────────────

def test_two_accounts_require_a_selection(browser, test_db, owner):
    m = _member(test_db)
    r = browser.get("/api/jobs")
    assert r.status_code == 401
    assert r.json() == {"detail": "account_required"}
    assert r.headers.get("X-JN-Auth") == "account"
    # the picker and public paths still answer
    assert browser.get("/health").status_code == 200
    accounts = browser.get("/api/auth/accounts")
    assert accounts.status_code == 200
    assert accounts.json() == [
        {"id": str(owner.id), "name": owner.name, "color": owner.color, "role": "owner", "has_pin": False},
        {"id": str(m.id), "name": "Partner", "color": "#2e9e6b", "role": "member", "has_pin": False},
    ]
    # the install password still comes first
    browser.headers.pop("X-API-Key")
    assert browser.get("/api/auth/accounts").status_code == 401
    assert browser.get("/api/jobs").json() == {"detail": "API key required"}


def test_switch_without_pin_sets_a_per_browser_cookie(browser, test_db, owner):
    m = _member(test_db)
    _job(test_db, owner.id, "owner-job")
    _job(test_db, m.id, "member-job")
    r = _switch(browser, m.id)
    assert r.status_code == 200, r.text
    assert r.json()["account"]["id"] == str(m.id) and r.json()["via"] == "no_pin"
    cookie = r.headers["set-cookie"]
    assert "jn_account=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "Max-Age=2592000" in cookie
    assert _me(browser).json()["account"]["id"] == str(m.id)
    listing = browser.get("/api/jobs").text
    assert "owner-job" not in listing
    # a second browser (fresh cookie jar) has not picked anything
    browser.cookies.clear()
    assert browser.get("/api/jobs").json() == {"detail": "account_required"}
    # ...and the owner (no PIN yet) is allowed without one
    assert _switch(browser, owner.id).json()["via"] == "no_pin"
    assert _me(browser).json()["account"]["role"] == "owner"
    test_db.expire_all()
    assert test_db.query(Account).filter(Account.id == m.id).one().last_active_at is not None


def test_switch_to_unknown_account_is_404(browser, test_db):
    _member(test_db)
    assert _switch(browser, uuid.uuid4()).status_code == 404
    assert browser.post("/api/auth/switch", json={"account_id": "nope"}).status_code == 404


def test_member_pin_required_wrong_and_right(browser, test_db):
    m = _member(test_db, pin="4321")
    r = _switch(browser, m.id)
    assert (r.status_code, r.json()) == (401, {"detail": "pin_required"})
    r = _switch(browser, m.id, "1111")
    assert (r.status_code, r.json()) == (401, {"detail": "wrong_pin", "tries_left": 4})
    assert "jn_account" not in browser.cookies
    r = _switch(browser, m.id, "4321")
    assert r.status_code == 200 and r.json()["via"] == "own_pin"
    acc = _me(browser).json()["account"]
    assert (acc["id"], acc["has_pin"]) == (str(m.id), True)


def test_owner_pin_required_once_set(browser, test_db, owner):
    _member(test_db)
    _set_pin(test_db, owner, "9999")
    assert _switch(browser, owner.id).json() == {"detail": "pin_required"}
    assert _switch(browser, owner.id, "1234").status_code == 401
    assert _switch(browser, owner.id, "9999").json()["via"] == "own_pin"


def test_owner_pin_covers_a_member_pin(browser, test_db, owner):
    m = _member(test_db, pin="4321")
    _set_pin(test_db, owner, "9999")
    r = _switch(browser, m.id, "9999")
    assert r.status_code == 200 and r.json()["via"] == "owner_pin"
    assert _me(browser).json()["account"]["id"] == str(m.id)
    # a member PIN does not open the owner
    assert _switch(browser, owner.id, "4321").json()["detail"] == "wrong_pin"


def test_member_without_pin_needs_none_even_when_owner_has_one(browser, test_db, owner):
    m = _member(test_db)
    _set_pin(test_db, owner, "9999")
    assert _switch(browser, m.id).status_code == 200


def test_five_wrong_pins_cool_the_account_down_for_30s(browser, test_db, monkeypatch):
    m = _member(test_db, pin="4321")
    other = _member(test_db, name="Other", pin="5555")
    clock = [1000.0]
    monkeypatch.setattr(A, "_mono", lambda: clock[0])
    for left in (4, 3, 2, 1):
        assert _switch(browser, m.id, "0000").json() == {"detail": "wrong_pin", "tries_left": left}
    r = _switch(browser, m.id, "0000")
    assert r.status_code == 429 and r.json() == {"detail": "pin_cooldown"}
    assert r.headers["Retry-After"] == "30"
    clock[0] += 10
    r = _switch(browser, m.id, "4321")                       # even the right PIN waits
    assert r.status_code == 429 and r.headers["Retry-After"] == "20"
    # per target account: another account is unaffected
    assert _switch(browser, other.id, "5555").status_code == 200
    clock[0] += 21
    assert _switch(browser, m.id, "4321").status_code == 200
    # the counter starts over after a success
    assert _switch(browser, m.id, "0000").json()["tries_left"] == 4


def test_wrong_pins_against_a_member_also_count_against_the_owner_pin(browser, test_db, owner, monkeypatch):
    m = _member(test_db, pin="4321")
    _set_pin(test_db, owner, "9999")
    clock = [1000.0]
    monkeypatch.setattr(A, "_mono", lambda: clock[0])
    for _ in range(5):
        _switch(browser, m.id, "0000")
    assert _switch(browser, owner.id, "9999").status_code == 429


# ── the cookie ───────────────────────────────────────────────────────────────

def _forge(value, **changes):
    body, sig = value.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload.update(changes)
    new_body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True)
                                        .encode()).rstrip(b"=").decode()
    return f"{new_body}.{sig}"


def test_tampered_cookie_is_rejected(browser, test_db, owner):
    m = _member(test_db)
    assert _switch(browser, m.id).status_code == 200
    good = browser.cookies.get("jn_account")
    for bad in (_forge(good, a=str(owner.id)),           # payload changed, old signature
                good[:-2] + ("AA" if not good.endswith("AA") else "BB"),   # signature changed
                good.split(".")[0],                       # no signature
                "x" + good):
        browser.cookies.clear()
        browser.cookies.set("jn_account", bad)
        r = browser.get("/api/jobs")
        assert (r.status_code, r.json()) == (401, {"detail": "account_required"}), bad
    browser.cookies.clear()
    browser.cookies.set("jn_account", good)
    assert _me(browser).json()["account"]["id"] == str(m.id)


def test_cookie_is_signed_with_the_install_secret(browser, test_db, owner):
    m = _member(test_db)
    _switch(browser, m.id)
    secret = test_db.query(Setting).filter(Setting.key == "account_cookie_secret",
                                           Setting.account_id.is_(None)).one().value
    assert len(secret) == 64
    payload = A.read_cookie(secret.encode(), browser.cookies.get("jn_account"))
    assert payload["a"] == str(m.id) and payload["u"] == 0
    # a cookie signed with another key is not accepted
    forged = A.sign_cookie(b"other-key", {**payload})
    browser.cookies.clear()
    browser.cookies.set("jn_account", forged)
    assert browser.get("/api/jobs").status_code == 401
    # never served, not writable
    settings = browser.get("/api/settings", headers={"X-Account": str(owner.id)}).json()
    assert "account_cookie_secret" not in settings
    r = browser.patch("/api/settings", json={"account_cookie_secret": "x"},
                      headers={"X-Account": str(owner.id)})
    assert r.status_code == 400


def test_expired_cookie_is_rejected(browser, test_db, monkeypatch):
    m = _member(test_db)
    _switch(browser, m.id)
    later = time.time() + A.COOKIE_MAX_AGE + 5
    monkeypatch.setattr(A, "_now", lambda: later)
    assert browser.get("/api/jobs").json() == {"detail": "account_required"}


def test_cookie_dies_with_a_pin_change_or_the_account(browser, test_db):
    m = _member(test_db)
    other = _member(test_db, name="Other")
    _switch(browser, m.id)
    _set_pin(test_db, m, "1234")
    assert browser.get("/api/jobs").json() == {"detail": "account_required"}
    browser.cookies.clear()
    _switch(browser, other.id)
    test_db.delete(other)
    test_db.commit()
    assert browser.get("/api/jobs").json() == {"detail": "account_required"}


# ── the API path: X-Account ──────────────────────────────────────────────────

def test_x_account_header_selects_the_account_without_pin(client, test_db, owner):
    m = _member(test_db, pin="4321")
    client.headers["X-Account"] = str(m.id)
    assert _me(client).json()["account"]["id"] == str(m.id)
    client.headers["X-Account"] = str(owner.id)
    assert _me(client).json()["account"]["id"] == str(owner.id)
    # the header wins over a cookie
    client.headers.pop("X-Account")
    _switch(client, owner.id)
    assert _me(client).json()["account"]["role"] == "owner"
    assert client.get("/api/auth/me", headers={"X-Account": str(m.id)}).json()["account"]["id"] == str(m.id)


@pytest.mark.parametrize("value", ["not-a-uuid", str(uuid.uuid4())])
def test_invalid_x_account_is_401(client, test_db, value):
    _member(test_db)
    client.headers["X-Account"] = value
    r = client.get("/api/jobs")
    assert (r.status_code, r.json()) == (401, {"detail": "invalid_account"})
    # even with one account
    test_db.query(Account).filter(Account.role == "member").delete()
    test_db.commit()
    assert client.get("/api/jobs").status_code == 401


def test_x_account_needs_the_header_key_not_just_the_session_cookie(client, test_db):
    m = _member(test_db)
    client.headers.pop("X-API-Key")
    client.headers["X-Account"] = str(m.id)
    client.cookies.set("jn_session", API_KEY)
    # a browser holding only jn_session cannot skip the picker/PIN with a header
    assert client.get("/api/jobs").json() == {"detail": "account_required"}


# ── member restrictions ──────────────────────────────────────────────────────

INSTALL_JOBS = [("POST", "/api/db/backup", None), ("POST", "/api/h1b/refresh", None)]
# MT-16: the LinkedIn session refresh and its PIN drop act on the caller's own session files
ACCOUNT_JOBS = [("POST", "/api/linkedin/session/refresh", None),
                ("POST", "/api/linkedin/session/pin", {"pin": "123456"})]


@pytest.fixture
def no_launch(monkeypatch, tmp_path):
    calls = []

    def _launch(job_type, *a, **k):
        calls.append(job_type)
        return "run-1"
    import backend.main as main_mod
    from backend.api import routes_linkedin
    from backend.accounts import credentials
    monkeypatch.setattr(main_mod, "launch_background", _launch)
    monkeypatch.setattr(routes_linkedin, "launch_background", _launch)
    monkeypatch.setattr(credentials, "LI_PIN_OWNER", str(tmp_path / "li_pin.txt"))
    return calls


@pytest.mark.parametrize("method,path,body", INSTALL_JOBS)
def test_member_cannot_start_install_level_jobs(browser, test_db, no_launch, method, path, body):
    m = _member(test_db)
    _switch(browser, m.id)
    r = browser.request(method, path, json=body)
    assert (r.status_code, r.json()) == (403, {"detail": "owner_only"})
    # also through the API path
    r = browser.request(method, path, json=body, headers={"X-Account": str(m.id)})
    assert r.status_code == 403
    assert no_launch == []


@pytest.mark.parametrize("method,path,body", INSTALL_JOBS + ACCOUNT_JOBS)
def test_owner_can_start_install_level_jobs(client, test_db, no_launch, method, path, body):
    _member(test_db)
    r = client.request(method, path, json=body)
    assert r.status_code in (200, 202), r.text


@pytest.mark.parametrize("method,path,body", ACCOUNT_JOBS)
def test_member_can_start_its_own_session_jobs(browser, test_db, no_launch, method, path, body):
    m = _member(test_db)
    _switch(browser, m.id)
    r = browser.request(method, path, json=body)
    assert r.status_code in (200, 202), r.text


def test_member_owner_only_settings_write_is_still_403(browser, test_db):
    m = _member(test_db)
    _switch(browser, m.id)
    r = browser.patch("/api/settings", json={"proxy_url": "socks5://x"})
    assert r.status_code == 403


# ── owner unlock ─────────────────────────────────────────────────────────────

def test_verify_owner_pin_unlocks_for_15_minutes(browser, test_db, owner):
    m = _member(test_db)
    _set_pin(test_db, owner, "9999")
    _switch(browser, m.id)
    assert _me(browser).json()["owner_unlocked_until"] is None
    r = browser.post("/api/auth/verify-owner-pin", json={"pin": "1111"})
    assert (r.status_code, r.json()) == (401, {"detail": "wrong_pin", "tries_left": 4})
    assert browser.post("/api/auth/verify-owner-pin", json={}).json() == {"detail": "pin_required"}
    before = time.time()
    r = browser.post("/api/auth/verify-owner-pin", json={"pin": "9999"})
    assert r.status_code == 200 and r.json()["ok"] is True
    me = _me(browser).json()
    assert me["account"]["id"] == str(m.id)                  # still the member
    from datetime import datetime
    until = datetime.fromisoformat(me["owner_unlocked_until"]).timestamp()
    assert before + 15 * 60 - 2 <= until <= time.time() + 15 * 60 + 1
    assert me["owner_unlocked_until"] == r.json()["unlocked_until"]


def test_verify_owner_pin_without_an_owner_pin_is_ok(browser, test_db):
    m = _member(test_db)
    _switch(browser, m.id)
    r = browser.post("/api/auth/verify-owner-pin", json={})
    assert r.status_code == 200 and r.json()["unlocked_until"]


def test_verify_owner_pin_needs_an_account(browser, test_db, owner):
    _member(test_db)
    _set_pin(test_db, owner, "9999")
    r = browser.post("/api/auth/verify-owner-pin", json={"pin": "9999"})
    assert (r.status_code, r.json()) == (401, {"detail": "account_required"})


def test_logout_clears_both_cookies(browser, test_db):
    m = _member(test_db)
    _switch(browser, m.id)
    r = browser.post("/api/auth/logout")
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("jn_session=") for c in cookies)
    assert any(c.startswith("jn_account=") for c in cookies)
