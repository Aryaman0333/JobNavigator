"""Routes the MT-3 leak harness (test_mt_leaks.py) does not call, because they are
install-wide by design or act on install-level state outside the database.

Key: (METHOD, path template exactly as FastAPI registers it). Value: one-line reason.
A stale entry (route renamed or removed) fails `test_allowlist_entries_exist`.
Do not park a route here because it leaks: mark it in KNOWN_LEAKS in test_mt_leaks.py.
"""

ALLOWLIST: dict[tuple[str, str], str] = {
    # Install password and liveness
    ("POST", "/api/auth/verify"): "install password check; the account cookie arrives in MT-10",
    ("POST", "/api/auth/set-session"): "install password session cookie (MT-10 adds the account cookie)",
    ("POST", "/api/auth/logout"): "clears the install session cookie",
    ("GET", "/health"): "liveness probe, no user data",

    # Settings (MT-9): A is the owner, whose view IS the install values; members' own rows
    # are not AccountScoped (Setting is read explicitly), so the harness seeds none.
    # test_mt_settings.py covers member reads/writes and that the owner never sees a
    # member's own values. /settings/sections and /settings/policies go through the harness.
    ("GET", "/api/settings"): "owner = install values; member/own-row isolation in test_mt_settings.py",
    ("PATCH", "/api/settings"): "owner writes install values + reconfigures the scheduler; member writes in test_mt_settings.py",
    ("GET", "/api/settings/defaults"): "static seed defaults",

    # Static catalogs
    ("GET", "/api/resumes/templates"): "template files on disk, shared by every account",
    ("GET", "/api/cover-letters/templates"): "template files on disk, shared by every account",
    ("GET", "/api/llm/efforts"): "static reasoning-effort catalog",
    ("GET", "/api/llm/models"): "provider model catalog fetched over the network",
    ("GET", "/api/searches/countries"): "static country list",

    # Install-level sessions and bots (per-account in MT-16 / MT-17)
    ("GET", "/api/linkedin/session"): "install LinkedIn cookie file until MT-16",
    ("POST", "/api/linkedin/session/refresh"): "writes the install LinkedIn cookie dir (MT-16)",
    ("POST", "/api/linkedin/session/pin"): "writes the install LinkedIn cookie dir (MT-16)",
    ("POST", "/api/telegram/webhook"): "public bot webhook; chat id -> account routing is MT-17",
    ("POST", "/api/telegram/register-webhook"): "install bot until MT-17",
    ("POST", "/api/telegram/rotate-webhook-secret"): "install bot until MT-17",
    ("POST", "/api/telegram/test"): "install bot until MT-17",

    # Install-level system work (stays install-level per MT-7)
    ("GET", "/api/scheduler/jobs"): "the one process-wide APScheduler",
    ("POST", "/api/db/backup"): "pg_dump of the whole install (owner/system)",
    ("POST", "/api/h1b/refresh"): "install-wide visa cache refresh",

    # Public tracer redirects: resolve any account's token by design; MT-6 looks the
    # token up unscoped and records the click under the link's own account.
    ("GET", "/cv/{token}"): "public tracer redirect, resolves any account's token by design",
    ("GET", "/"): "public ?cv= tracer redirect, resolves any account's token by design",
}
