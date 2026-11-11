"""Shared runtime state passed to every handler."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .config import Config
from .database import Database

if TYPE_CHECKING:
    from pyrogram import Client

    from .scheduler import ChannelLoop

log = logging.getLogger(__name__)


# Keys used in the `settings` table.
class Keys:
    LOOP_ENABLED = "loop_enabled"
    LOOP_INTERVAL = "loop_interval"
    LOOP_TEXT = "loop_text"
    LOOP_LAST_MESSAGE_ID = "loop_last_message_id"
    LOOP_MEDIA_TYPE = "loop_media_type"        # photo/video/animation, or "none"
    LOOP_MEDIA_FILE_ID = "loop_media_file_id"  # set via /loopmedia
    LOOP_MEDIA_CACHE = "loop_media_cache"      # "<.env source>\n<file_id>" after 1st upload
    ANNOUNCE_ENABLED = "announce_enabled"
    PERMANENT_LINK = "permanent_invite_link"


@dataclass
class BotContext:
    config: Config
    db: Database
    bot_id: int = 0
    bot_username: str = ""
    loop: "ChannelLoop | None" = None

    _user_locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    _last_verify: dict[int, float] = field(default_factory=dict)
    _admin_alerts: dict[str, float] = field(default_factory=dict)
    broadcast_running: bool = False
    background_tasks: set[asyncio.Task] = field(default_factory=set)

    def spawn(self, coro) -> asyncio.Task:
        """create_task that keeps a strong reference until the task finishes."""
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        return task

    # ------------------------------------------------------------------ #
    @property
    def quest_deep_link(self) -> str:
        return f"https://t.me/{self.bot_username}?start=quest"

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.config.admin_ids

    def user_lock(self, user_id: int) -> asyncio.Lock:
        """Per-user lock so concurrent Verify clicks are processed one at a time."""
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = self._user_locks[user_id] = asyncio.Lock()
        return lock

    def verify_cooldown_left(self, user_id: int) -> float:
        """Seconds left before this user may press Verify again (0 = allowed).

        Calling this when it returns 0 starts a new cooldown window.
        """
        cooldown = self.config.verify_cooldown_seconds
        if cooldown <= 0:
            return 0.0
        now = time.monotonic()
        last = self._last_verify.get(user_id)
        if last is not None and now - last < cooldown:
            return cooldown - (now - last)
        self._last_verify[user_id] = now
        return 0.0

    async def notify_admins(
        self, client: "Client", text: str, *, dedupe_key: str | None = None,
        dedupe_seconds: int = 600,
    ) -> None:
        """DM every admin. With ``dedupe_key`` the same alert is sent at most
        once per ``dedupe_seconds`` (avoids flooding admins with repeats)."""
        if dedupe_key:
            now = time.monotonic()
            last = self._admin_alerts.get(dedupe_key)
            if last is not None and now - last < dedupe_seconds:
                return
            self._admin_alerts[dedupe_key] = now
        for admin_id in self.config.admin_ids:
            try:
                await client.send_message(admin_id, text)
            except Exception as exc:  # admin never started the bot, etc.
                log.warning("Could not notify admin %s: %s", admin_id, exc)
