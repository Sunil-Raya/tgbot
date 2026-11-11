"""Invite-link issuing and the public announcement."""

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import User

from . import texts
from .context import BotContext, Keys
from .membership import is_member

log = logging.getLogger(__name__)


async def _permanent_link(client: Client, ctx: BotContext) -> str:
    """One shared, non-expiring link (configured, or created once and cached)."""
    if ctx.config.permanent_invite_link:
        return ctx.config.permanent_invite_link
    cached = await ctx.db.get_setting(Keys.PERMANENT_LINK)
    if cached:
        return cached
    link = await client.create_chat_invite_link(
        ctx.config.private_channel_id, name="quest-permanent"
    )
    await ctx.db.set_setting(Keys.PERMANENT_LINK, link.invite_link)
    return link.invite_link


async def _unique_link(client: Client, ctx: BotContext, user_id: int) -> str:
    """Single-use link that only lets one person in (cannot be re-shared)."""
    link = await client.create_chat_invite_link(
        ctx.config.private_channel_id,
        name=f"quest-{user_id}"[:32],
        member_limit=1,
    )
    return link.invite_link


async def revoke_link(client: Client, ctx: BotContext, invite_link: str | None) -> None:
    """Revoke a per-user link. Shared/permanent links are never revoked here."""
    if not invite_link or ctx.config.invite_link_mode != "unique":
        return
    try:
        await client.revoke_chat_invite_link(ctx.config.private_channel_id, invite_link)
    except RPCError as exc:
        log.warning("Could not revoke invite link %s: %s", invite_link, exc)


async def issue_new_link(client: Client, ctx: BotContext, user_id: int) -> str:
    if ctx.config.invite_link_mode == "permanent":
        return await _permanent_link(client, ctx)
    return await _unique_link(client, ctx, user_id)


async def link_for_returning_user(
    client: Client, ctx: BotContext, user_id: int, stored_link: str | None
) -> str:
    """Link for a user who already completed the quest.

    In ``unique`` mode a single-use link is useless once consumed, so if the
    user is no longer in the private channel (left, or never used it) we revoke
    the old link and hand out a fresh one.
    """
    if ctx.config.invite_link_mode == "permanent":
        return await _permanent_link(client, ctx)

    in_channel = await is_member(client, ctx.config.private_channel_id, user_id)
    if stored_link and in_channel is not False:
        return stored_link
    await revoke_link(client, ctx, stored_link)
    new_link = await _unique_link(client, ctx, user_id)
    await ctx.db.set_invite_link(user_id, new_link)
    return new_link


async def announce_unlock(client: Client, ctx: BotContext, user: User) -> None:
    """Public "🎉 User X just unlocked the private channel!" post."""
    if not await ctx.db.get_bool(Keys.ANNOUNCE_ENABLED, ctx.config.announce_enabled_default):
        return
    try:
        await client.send_message(
            ctx.config.announce_channel_id,
            texts.announcement_text(user.first_name),
            reply_markup=texts.announcement_keyboard(ctx.quest_deep_link),
        )
    except RPCError as exc:
        log.error("Announcement failed: %s", exc)
        await ctx.notify_admins(
            client,
            f"⚠️ Could not post the unlock announcement: <code>{exc}</code>",
            dedupe_key="announce-failed",
        )
