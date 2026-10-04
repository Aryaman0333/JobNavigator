"""Whole-database snapshots with pg_dump (install-level, owner only).

One function for the three callers: the scheduled backup (`scheduler.run_db_backup`),
the manual trigger (`POST /api/db/backup`) and the automatic snapshot taken before an
account is removed (`DELETE /api/accounts/{id}`, MT-11).
"""
import glob
import os
import subprocess
from datetime import datetime
from urllib.parse import urlparse

BACKUP_DIR = "/app/backups"
ROTATION_PREFIX = "jobnavigator_"   # the scheduled/manual rotation (last 5 kept)
KEEP = 5


def run_pg_dump(prefix: str = ROTATION_PREFIX, suffix: str = "", rotate: bool = True) -> dict:
    """Dump the database to `<BACKUP_DIR>/<prefix><timestamp><suffix>.sql`.

    Returns {"path", "file", "size_mb", "pruned"}; raises RuntimeError when pg_dump fails
    (non-zero exit), so a caller that must not continue without a snapshot can abort.
    With `rotate`, only the newest KEEP files of the rotation prefix are kept."""
    from backend.config import DATABASE_URL

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{BACKUP_DIR}/{prefix}{timestamp}{suffix}.sql"

    parsed = urlparse(DATABASE_URL)
    if not parsed.hostname or not parsed.scheme.startswith("postgres"):
        raise RuntimeError("pg_dump needs a PostgreSQL database")
    env = os.environ.copy()
    env["PGPASSWORD"] = parsed.password or ""

    result = subprocess.run(
        ["pg_dump", "-h", parsed.hostname, "-p", str(parsed.port or 5432),
         "-U", parsed.username, "-d", parsed.path.lstrip("/"),
         "-f", backup_file],
        env=env, capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    pruned = 0
    if rotate:
        backups = sorted(glob.glob(f"{BACKUP_DIR}/{ROTATION_PREFIX}*.sql"))
        while len(backups) > KEEP:
            os.remove(backups.pop(0))
            pruned += 1

    size_mb = os.path.getsize(backup_file) / (1024 * 1024)
    return {"path": backup_file, "file": os.path.basename(backup_file),
            "size_mb": size_mb, "pruned": pruned}
