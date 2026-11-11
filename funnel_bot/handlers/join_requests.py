"""Auto-approve every join request to the private channel."""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError, UserAlreadyParticipant
from pyrogram.handlers import ChatJoinRequestHandler
from pyrogram.types import ChatJoinRequest

from .. import texts
from ..context import BotContext

log = logging.getLogger(__name__)


def register(app: Client, ctx: BotContext) -> None:
    cfg = ctx.config

    async def on_join_request(client: Client, request: ChatJoinRequest) -> None:
        user = request.from_user
        row = await ctx.db.get_user(user.id)
        if row and row.is_banned:
            try:
                await request.decline()
            except RPCError as exc:
                log.warning("Could not decline banned user %s: %s", user.id, exc)
            await ctx.db.log_join_request(user.id, request.chat.id, False, "banned")
            log.info("Declined join request from banned user %s", user.id)
            return

        approved, error = False, None
        for attempt in range(3):
            try:
                await request.approve()
                approved = True
                break
            except UserAlreadyParticipant:
                approved = True
                break
            except FloodWait as exc:
                log.warning("FloodWait %ss approving %s", exc.value, user.id)
                await asyncio.sleep(float(exc.value) + 1)
            except RPCError as exc:
                error = f"{type(exc).__name__}: {exc}"
                log.error("Could not approve join request of %s: %s", user.id, exc)
                break

        await ctx.db.upsert_user(user.id, user.first_name, user.username)
        await ctx.db.log_join_request(user.id, request.chat.id, approved, error)

        if not approved:
            await ctx.notify_admins(
                client,
                f"⚠️ Failed to approve a join request: <code>{error}</code>\n"
                "Make sure the bot has the <b>Add Members / Invite users</b> right.",
                dedupe_key="join-approve-failed",
            )
            return

        log.info("Approved join request from %s (%s)", user.id, user.first_name)
        if cfg.welcome_dm_on_join and ctx.bot_username:
            # Bots may DM users who sent a join request, even before /start.
            try:
                await client.send_message(
                    user.id,
                    texts.join_welcome_text(user.first_name),
                    reply_markup=texts.start_quest_keyboard(ctx.quest_deep_link),
                )
            except RPCError as exc:
                log.debug("Welcome DM to %s failed: %s", user.id, exc)

    app.add_handler(
        ChatJoinRequestHandler(on_join_request, filters.chat(cfg.private_channel_id))
    )
