"""Core quest logic, independent of how the result is rendered."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from pyrogram import Client
from pyrogram.types import User

from .context import BotContext
from .membership import check_channels
from .rewards import announce_unlock, issue_new_link, link_for_returning_user, revoke_link

log = logging.getLogger(__name__)


class Outcome(str, Enum):
    BANNED = "banned"            # blocked by an admin
    ALREADY_DONE = "already"     # completed earlier -> just resend the link
    COMPLETED = "completed"      # completed right now
    MISSING = "missing"          # not subscribed to at least one channel
    CHECK_ERROR = "error"        # Telegram/permission error while checking


@dataclass
class VerifyResult:
    outcome: Outcome
    status: dict[str, bool | None] = field(default_factory=dict)
    link: str | None = None


async def verify_user(client: Client, ctx: BotContext, user: User) -> VerifyResult:
    """Database check -> Telegram membership check -> reward + announcement.

    Serialised per user, and ``mark_completed`` is atomic, so spamming the
    Verify button can never produce two links or two announcements.
    """
    async with ctx.user_lock(user.id):
        await ctx.db.upsert_user(user.id, user.first_name, user.username, started=True)
        row = await ctx.db.get_user(user.id)
        assert row is not None

        if row.is_banned:
            return VerifyResult(Outcome.BANNED)

        # 1) Database: users who already finished never repeat the quest.
        if row.completed:
            link = await link_for_returning_user(client, ctx, user.id, row.invite_link)
            return VerifyResult(Outcome.ALREADY_DONE, link=link)

        # 2) Telegram API: are they subscribed to every required channel right now?
        await ctx.db.record_verify_attempt(user.id)
        status = await check_channels(client, ctx.config.required_channels, user.id)
        if any(v is False for v in status.values()):
            return VerifyResult(Outcome.MISSING, status=status)
        if any(v is None for v in status.values()):
            return VerifyResult(Outcome.CHECK_ERROR, status=status)

        # 3) Reward.
        link = await issue_new_link(client, ctx, user.id)
        first_time = await ctx.db.mark_completed(user.id, link)
        if first_time:
            log.info("User %s (%s) completed the quest", user.id, user.first_name)
            # 4) Public announcement.
            await announce_unlock(client, ctx, user)
            return VerifyResult(Outcome.COMPLETED, status=status, link=link)

        # Extremely unlikely (row changed between read and write): treat as done
        # and revoke the link we just created so it isn't left dangling.
        row = await ctx.db.get_user(user.id)
        if row and row.invite_link != link:
            await revoke_link(client, ctx, link)
        return VerifyResult(Outcome.ALREADY_DONE, link=(row.invite_link if row else link))
