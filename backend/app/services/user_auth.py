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
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, Response, status

from app.config import DB_PATH
from app.core.app_config import AppConfig
from app.services.audit import audit_service
from app.storage.db import initialize_database

SESSION_COOKIE_NAME = "legadohub_session"
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 240_000
USERNAME_MAX_LENGTH = 64
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
ALLOWED_ROLES = {"admin", "user"}


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

    @contextmanager
    def _conn(self):
        initialize_database(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

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

    def _validate_username(self, username: str) -> str:
        username = str(username or "").strip()
        if not username:
            raise HTTPException(status_code=400, detail="用户名不能为空")
        if len(username) > USERNAME_MAX_LENGTH:
            raise HTTPException(status_code=400, detail=f"用户名不能超过 {USERNAME_MAX_LENGTH} 个字符")
        if any(character.isspace() or ord(character) < 32 for character in username):
            raise HTTPException(status_code=400, detail="用户名不能包含空白或控制字符")
        return username

    def _validate_password(self, password: str) -> str:
        password = str(password or "")
        if len(password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(status_code=400, detail=f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符")
        if len(password) > PASSWORD_MAX_LENGTH:
            raise HTTPException(status_code=400, detail=f"密码不能超过 {PASSWORD_MAX_LENGTH} 个字符")
        if any(ord(character) < 32 for character in password):
            raise HTTPException(status_code=400, detail="密码不能包含控制字符")
        return password

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        *,
        require_empty: bool = False,
        actor_user_id: str = "",
        actor_role: str = "",
    ) -> dict[str, Any]:
        username = self._validate_username(username)
        password = self._validate_password(password)
        role = str(role or "").strip()
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=400, detail="角色必须是 admin 或 user")
        user_id = uuid.uuid4().hex
        now = self._now()
        password_hash = self.hash_password(password)
        try:
            with self._conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if require_empty:
                    existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()
                    if int(existing[0] or 0) > 0:
                        raise HTTPException(status_code=409, detail="系统已存在用户，不能再次初始化管理员")
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, password_hash, role, disabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (user_id, username, password_hash, role, now, now),
                )
                if actor_user_id:
                    audit_service.record(
                        action="user.create",
                        actor_user_id=actor_user_id,
                        actor_role=actor_role,
                        target_type="user",
                        target_id=user_id,
                        summary={"role": role, "disabled": False},
                        conn=conn,
                    )
                conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="用户名已存在")
        return {"userId": user_id, "username": username, "role": role, "disabled": False}

    def bootstrap_admin(self, username: str, password: str | None = None) -> dict[str, Any]:
        if password is None:
            password = self._admin_password_from_config()
        if not password:
            password = secrets.token_urlsafe(12)
            config = AppConfig.get()
            config.set(
                "auth.adminPasswordBase64",
                base64.b64encode(password.encode("utf-8")).decode("ascii"),
            )
            config.save()
        return self.create_user(
            username=username,
            password=password,
            role="admin",
            require_empty=True,
        )

    def ensure_default_admin(self, username: str = "admin") -> str | None:
        if self.user_count() > 0:
            return None
        password = self._admin_password_from_config()
        if not password:
            password = secrets.token_urlsafe(12)
            config = AppConfig.get()
            config.set(
                "auth.adminPasswordBase64",
                base64.b64encode(password.encode("utf-8")).decode("ascii"),
            )
            config.save()
        self.bootstrap_admin(username=username, password=password)
        return password

    def reset_password(
        self,
        user_id: str,
        password: str,
        *,
        invalidate_sessions: bool = True,
        actor_user_id: str = "",
        actor_role: str = "",
    ) -> dict[str, Any]:
        password = self._validate_password(password)
        now = self._now()
        password_hash = self.hash_password(password)
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                (password_hash, now, user_id),
            )
            if cursor.rowcount > 0 and invalidate_sessions:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            if cursor.rowcount > 0 and actor_user_id:
                audit_service.record(
                    action="user.password.reset",
                    actor_user_id=actor_user_id,
                    actor_role=actor_role,
                    target_type="user",
                    target_id=user_id,
                    conn=conn,
                )
            conn.commit()
        if cursor.rowcount <= 0:
            raise HTTPException(status_code=404, detail="用户不存在")

        # Keep the configured admin password in sync with app_config.json so the
        # file remains the single source of truth.
        user = self.get_user(user_id)
        if user and user.username == "admin":
            config = AppConfig.get()
            config.set("auth.adminPasswordBase64", base64.b64encode(password.encode("utf-8")).decode("ascii"))
            config.save()

        return {"userId": user_id, "passwordReset": True}

    def change_password(self, user: AuthUser, current_password: str, new_password: str) -> dict[str, Any]:
        self.authenticate(user.username, current_password)
        return self.reset_password(user.user_id, new_password, invalidate_sessions=False)

    def set_disabled(
        self,
        user_id: str,
        disabled: bool,
        *,
        actor_user_id: str = "",
        actor_role: str = "",
    ) -> dict[str, Any]:
        now = self._now()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                "SELECT role, disabled FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            if disabled and actor_user_id and user_id == actor_user_id:
                raise HTTPException(status_code=409, detail="不能禁用当前登录的管理员")
            if disabled and target[0] == "admin" and not bool(target[1]):
                enabled_admins = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0"
                ).fetchone()
                if int(enabled_admins[0] or 0) <= 1:
                    raise HTTPException(status_code=409, detail="系统必须保留至少一个可用管理员")
            cursor = conn.execute(
                "UPDATE users SET disabled = ?, updated_at = ? WHERE user_id = ?",
                (1 if disabled else 0, now, user_id),
            )
            if disabled:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            if actor_user_id:
                audit_service.record(
                    action="user.disable" if disabled else "user.enable",
                    actor_user_id=actor_user_id,
                    actor_role=actor_role,
                    target_type="user",
                    target_id=user_id,
                    summary={"role": target[0], "disabled": bool(disabled)},
                    conn=conn,
                )
            conn.commit()
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

    def _admin_password_from_config(self) -> str | None:
        """Return the admin password configured in app_config.json, if any."""
        return AppConfig.get().auth.admin_password()

    def authenticate(self, username: str, password: str) -> AuthUser:
        username = str(username or "").strip()
        supplied = str(password or "")
        row = self.get_user_by_username(username)
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

        # Admin password lives in app_config.json (base64 encoded) so it can be
        # adjusted without touching the database. Non-admin users still use the
        # password hash stored in the database.
        if username == "admin":
            config_password = self._admin_password_from_config()
            if config_password is not None:
                if not hmac.compare_digest(config_password, supplied):
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
            elif not self.verify_password(supplied, row["passwordHash"]):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        elif not self.verify_password(supplied, row["passwordHash"]):
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
