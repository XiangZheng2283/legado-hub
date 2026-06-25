"""Reset a LegadoHub user's password without deleting application data."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import DB_PATH
from app.services.user_auth import UserAuthService


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a LegadoHub user password safely.")
    parser.add_argument("--username", default="admin", help="Username to reset. Default: admin")
    parser.add_argument("--password", default="", help="New password. Omit to generate one.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help=f"Database path. Default: {DB_PATH}")
    args = parser.parse_args()

    service = UserAuthService(args.db)
    user = service.get_user_by_username(args.username)
    if not user:
        print(f"User not found: {args.username}", file=sys.stderr)
        return 1

    password = args.password or secrets.token_urlsafe(12)
    service.reset_password(user["userId"], password)
    print("Password reset.")
    print(f"  Database: {args.db}")
    print(f"  Username: {args.username}")
    print(f"  Password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
