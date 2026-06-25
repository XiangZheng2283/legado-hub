from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT


def main() -> int:
    script = PROJECT / "backend" / "scripts" / "run_shared_subscription_real_book.py"
    cmd = [
        str(PROJECT / ".venv" / "Scripts" / "python.exe"),
        str(script),
        "--rounds",
        "1",
        "--chapter-limit",
        "1",
        "--ensure-admin",
        "--rollback-created",
        "--rollback-created-admin",
        "--keep-temp-db",
    ]
    completed = subprocess.run(cmd, cwd=PROJECT, capture_output=True)
    if completed.returncode != 0:
        print(completed.stdout.decode("utf-8", errors="replace"))
        print(completed.stderr.decode("utf-8", errors="replace"))
        return completed.returncode or 1

    stdout = completed.stdout.decode("utf-8", errors="replace")
    data = json.loads(stdout)
    db_path = Path(data["dbPath"])
    with sqlite3.connect(db_path) as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        books = conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone()[0]
        chapters = conn.execute("SELECT COUNT(*) FROM aggregate_chapter_tasks").fetchone()[0]

    state = {
        "rollbackCreated": data.get("rollbackCreated"),
        "admin": data.get("admin", {}),
        "usersAfter": users,
        "booksAfter": books,
        "chaptersAfter": chapters,
    }
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if users != 0:
        print("expected created admin to be rolled back")
        return 1
    if books != 0 or chapters != 0:
        print("expected created aggregate book to be rolled back")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
