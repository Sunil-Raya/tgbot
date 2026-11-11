"""SQLite persistence layer (async, via aiosqlite).

Tables
------
users          one row per Telegram user who ever touched the bot
join_requests  audit log of join requests auto-approved in the private channel
settings       small key/value store for runtime state that must survive restarts
               (loop on/off, loop interval, last loop message id, ...)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    first_name      TEXT,
    username        TEXT,
    source          TEXT,                       -- deep-link payload of first /start
    started_at      INTEGER,                    -- first /start in DM (unix ts)
    completed       INTEGER NOT NULL DEFAULT 0, -- 1 once the quest is done
    completed_at    INTEGER,
    invite_link     TEXT,                       -- link handed out as reward
    verify_attempts INTEGER NOT NULL DEFAULT 0,
    last_verify_at  INTEGER,
    is_banned       INTEGER NOT NULL DEFAULT 0, -- banned by an admin from the bot
    is_blocked      INTEGER NOT NULL DEFAULT 0, -- user blocked the bot (broadcast failed)
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_completed ON users(completed);

CREATE TABLE IF NOT EXISTS join_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    chat_id      INTEGER NOT NULL,
    requested_at INTEGER NOT NULL,
    approved     INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_join_requests_user ON join_requests(user_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def now() -> int:
    return int(time.time())


@dataclass
class UserRow:
    user_id: int
    first_name: str | None
    username: str | None
    source: str | None
    started_at: int | None
    completed: bool
    completed_at: int | None
    invite_link: str | None
    verify_attempts: int
    last_verify_at: int | None
    is_banned: bool
    is_blocked: bool
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "UserRow":
        data = dict(row)
        data["completed"] = bool(data["completed"])
        data["is_banned"] = bool(data["is_banned"])
        data["is_blocked"] = bool(data["is_blocked"])
        return cls(**data)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    # ------------------------------------------------------------------ #
    # users
    # ------------------------------------------------------------------ #
    async def upsert_user(
        self,
        user_id: int,
        first_name: str | None,
        username: str | None,
        *,
        source: str | None = None,
        started: bool = False,
    ) -> None:
        """Create the user if new, otherwise refresh name/username.

        ``source`` and ``started_at`` are only written the first time.
        Starting the bot also clears ``is_blocked`` (they talk to us again).
        """
        ts = now()
        await self.conn.execute(
            """
            INSERT INTO users (user_id, first_name, username, source, started_at,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                username   = excluded.username,
                source     = COALESCE(users.source, excluded.source),
                started_at = COALESCE(users.started_at, excluded.started_at),
                is_blocked = CASE WHEN excluded.started_at IS NOT NULL
                                  THEN 0 ELSE users.is_blocked END,
                updated_at = excluded.updated_at
            """,
            (user_id, first_name, username, source, ts if started else None, ts, ts),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> UserRow | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return UserRow.from_row(row) if row else None

    async def record_verify_attempt(self, user_id: int) -> None:
        await self.conn.execute(
            """UPDATE users SET verify_attempts = verify_attempts + 1,
                                last_verify_at = ?, updated_at = ?
               WHERE user_id = ?""",
            (now(), now(), user_id),
        )
        await self.conn.commit()

    async def mark_completed(self, user_id: int, invite_link: str) -> bool:
        """Atomically flip ``completed`` 0 -> 1.

        Returns True only for the call that actually completed the quest, so
        double-clicks on "Verify" can never trigger two announcements.
        """
        ts = now()
        cur = await self.conn.execute(
            """UPDATE users SET completed = 1, completed_at = ?, invite_link = ?,
                                updated_at = ?
               WHERE user_id = ? AND completed = 0""",
            (ts, invite_link, ts, user_id),
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def set_invite_link(self, user_id: int, invite_link: str | None) -> None:
        await self.conn.execute(
            "UPDATE users SET invite_link = ?, updated_at = ? WHERE user_id = ?",
            (invite_link, now(), user_id),
        )
        await self.conn.commit()

    async def reset_user(self, user_id: int) -> bool:
        cur = await self.conn.execute(
            """UPDATE users SET completed = 0, completed_at = NULL, invite_link = NULL,
                                verify_attempts = 0, updated_at = ?
               WHERE user_id = ?""",
            (now(), user_id),
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def set_banned(self, user_id: int, banned: bool) -> None:
        ts = now()
        await self.conn.execute(
            """INSERT INTO users (user_id, is_banned, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET is_banned = excluded.is_banned,
                                                  updated_at = excluded.updated_at""",
            (user_id, int(banned), ts, ts),
        )
        await self.conn.commit()

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        await self.conn.execute(
            "UPDATE users SET is_blocked = ?, updated_at = ? WHERE user_id = ?",
            (int(blocked), now(), user_id),
        )
        await self.conn.commit()

    async def broadcast_targets(self) -> list[int]:
        """Users who started the bot in DM, are not banned and have not blocked it."""
        async with self.conn.execute(
            """SELECT user_id FROM users
               WHERE started_at IS NOT NULL AND is_banned = 0 AND is_blocked = 0
               ORDER BY user_id"""
        ) as cur:
            rows = await cur.fetchall()
        return [row["user_id"] for row in rows]

    async def find_user_by_username(self, username: str) -> UserRow | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.lstrip("@"),),
        ) as cur:
            row = await cur.fetchone()
        return UserRow.from_row(row) if row else None

    async def all_users(self) -> list[UserRow]:
        async with self.conn.execute("SELECT * FROM users ORDER BY created_at") as cur:
            rows = await cur.fetchall()
        return [UserRow.from_row(r) for r in rows]

    # ------------------------------------------------------------------ #
    # join requests
    # ------------------------------------------------------------------ #
    async def log_join_request(
        self, user_id: int, chat_id: int, approved: bool, error: str | None = None
    ) -> None:
        await self.conn.execute(
            """INSERT INTO join_requests (user_id, chat_id, requested_at, approved, error)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, chat_id, now(), int(approved), error),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------ #
    # stats
    # ------------------------------------------------------------------ #
    async def stats(self) -> dict[str, int]:
        day_ago = now() - 86_400
        queries = {
            "users_total": "SELECT COUNT(*) FROM users",
            "users_started": "SELECT COUNT(*) FROM users WHERE started_at IS NOT NULL",
            "completed_total": "SELECT COUNT(*) FROM users WHERE completed = 1",
            "completed_24h": f"SELECT COUNT(*) FROM users WHERE completed = 1 AND completed_at >= {day_ago}",
            "started_24h": f"SELECT COUNT(*) FROM users WHERE started_at >= {day_ago}",
            "banned": "SELECT COUNT(*) FROM users WHERE is_banned = 1",
            "blocked": "SELECT COUNT(*) FROM users WHERE is_blocked = 1",
            "join_approved_total": "SELECT COUNT(*) FROM join_requests WHERE approved = 1",
            "join_approved_24h": f"SELECT COUNT(*) FROM join_requests WHERE approved = 1 AND requested_at >= {day_ago}",
            "join_failed_total": "SELECT COUNT(*) FROM join_requests WHERE approved = 0",
        }
        result: dict[str, int] = {}
        for key, sql in queries.items():
            async with self.conn.execute(sql) as cur:
                row = await cur.fetchone()
            result[key] = int(row[0]) if row else 0
        return result

    # ------------------------------------------------------------------ #
    # settings (key/value)
    # ------------------------------------------------------------------ #
    async def get_setting(self, key: str, default: Any = None) -> str | Any:
        async with self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row and row["value"] is not None else default

    async def set_setting(self, key: str, value: Any) -> None:
        await self.conn.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, None if value is None else str(value)),
        )
        await self.conn.commit()

    async def get_bool(self, key: str, default: bool) -> bool:
        raw = await self.get_setting(key)
        return default if raw is None else raw == "1"

    async def set_bool(self, key: str, value: bool) -> None:
        await self.set_setting(key, "1" if value else "0")

    async def get_int(self, key: str, default: int | None) -> int | None:
        raw = await self.get_setting(key)
        try:
            return default if raw is None else int(raw)
        except ValueError:
            return default
