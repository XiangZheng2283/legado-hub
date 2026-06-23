"""Minimal user auth and admin helpers for subscription/library pages.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, Response, status

from app.config import DB_PATH
from app.storage.db import initialize_database

SESSION_COOKIE_NAME = "legadohub_session"
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 240_000


@dataclass
class AuthUser:
    user_id: str
    username: str
    role: str
    disabled: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class UserAuthService:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        initialize_database(self.db_path)
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _future(self, days: int = SESSION_TTL_DAYS) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    def user_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0] or 0)

    def list_users(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT user_id, username, role, disabled, created_at, updated_at
                FROM users
                ORDER BY created_at ASC, username ASC
                """
            ).fetchall()
        return [
            {
                "userId": row[0],
                "username": row[1],
                "role": row[2],
                "disabled": bool(row[3]),
                "createdAt": row[4],
                "updatedAt": row[5],
            }
            for row in rows
        ]

    def create_user(self, username: str, password: str, role: str = "user") -> dict[str, Any]:
        username = str(username or "").strip()
        password = str(password or "")
        role = "admin" if role == "admin" else "user"
        if not username:
            raise HTTPException(status_code=400, detail="用户名不能为空")
        if not password:
            raise HTTPException(status_code=400, detail="密码不能为空")
        user_id = uuid.uuid4().hex
        now = self._now()
        password_hash = self.hash_password(password)
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, password_hash, role, disabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (user_id, username, password_hash, role, now, now),
                )
                conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="用户名已存在")
        return {"userId": user_id, "username": username, "role": role, "disabled": False}

    def bootstrap_admin(self, username: str, password: str) -> dict[str, Any]:
        if self.user_count() > 0:
            raise HTTPException(status_code=409, detail="系统已存在用户，不能再次初始化管理员")
        return self.create_user(username=username, password=password, role="admin")

    def reset_password(self, user_id: str, password: str) -> dict[str, Any]:
        if not password:
            raise HTTPException(status_code=400, detail="密码不能为空")
        now = self._now()
        password_hash = self.hash_password(password)
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (password_hash, now, user_id),
            )
            conn.commit()
        if cursor.rowcount <= 0:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"userId": user_id, "passwordReset": True}

    def set_disabled(self, user_id: str, disabled: bool) -> dict[str, Any]:
        now = self._now()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE users SET disabled = ?, updated_at = ? WHERE user_id = ?",
                (1 if disabled else 0, now, user_id),
            )
            if disabled:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()
        if cursor.rowcount <= 0:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"userId": user_id, "disabled": bool(disabled)}

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT user_id, username, password_hash, role, disabled
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        if not row:
            return None
        return {
            "userId": row[0],
            "username": row[1],
            "passwordHash": row[2],
            "role": row[3],
            "disabled": bool(row[4]),
        }

    def get_user(self, user_id: str) -> AuthUser | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT user_id, username, role, disabled
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return AuthUser(
            user_id=row[0],
            username=row[1],
            role=row[2],
            disabled=bool(row[3]),
        )

    def hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return "pbkdf2_sha256${}${}${}".format(
            PBKDF2_ITERATIONS,
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )

    def verify_password(self, password: str, stored: str) -> bool:
        try:
            scheme, iterations, salt_b64, digest_b64 = stored.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
            return hmac.compare_digest(expected, actual)
        except Exception:
            return False

    def authenticate(self, username: str, password: str) -> AuthUser:
        row = self.get_user_by_username(str(username or "").strip())
        if not row or not self.verify_password(str(password or ""), row["passwordHash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        if row["disabled"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")
        user = self.get_user(row["userId"])
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
        return user

    def create_session(self, user: AuthUser) -> str:
        session_id = secrets.token_urlsafe(32)
        now = self._now()
        expires = self._future()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO user_sessions (session_id, user_id, expires_at, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user.user_id, expires, now, now),
            )
            conn.commit()
        return session_id

    def destroy_session(self, session_id: str) -> None:
        if not session_id:
            return
        with self._conn() as conn:
            conn.execute("DELETE FROM user_sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    def _get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT session_id, user_id, expires_at
                FROM user_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return {"sessionId": row[0], "userId": row[1], "expiresAt": row[2]}

    def _is_expired(self, expires_at: str) -> bool:
        try:
            return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
        except Exception:
            return True

    def current_user(self, request: Request, *, touch: bool = True) -> AuthUser | None:
        session_id = request.cookies.get(SESSION_COOKIE_NAME, "")
        if not session_id:
            return None
        session = self._get_session(session_id)
        if not session:
            return None
        if self._is_expired(session["expiresAt"]):
            self.destroy_session(session_id)
            return None
        user = self.get_user(session["userId"])
        if not user or user.disabled:
            self.destroy_session(session_id)
            return None
        if touch:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE user_sessions SET last_seen_at = ? WHERE session_id = ?",
                    (self._now(), session_id),
                )
                conn.commit()
        return user

    def require_user(self, request: Request) -> AuthUser:
        user = self.current_user(request)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        return user

    def require_admin(self, request: Request) -> AuthUser:
        user = self.require_user(request)
        if not user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
        return user

    def set_session_cookie(self, response: Response, session_id: str) -> None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")


auth_service = UserAuthService()
