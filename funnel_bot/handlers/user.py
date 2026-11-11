"""Handlers for regular users: /start (incl. ?start=quest deep link), /help,
and the Verify button."""

from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, RPCError
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import CallbackQuery, Message

from .. import texts
from ..context import BotContext
from ..quest import Outcome, verify_user
from ..rewards import link_for_returning_user

log = logging.getLogger(__name__)


def register(app: Client, ctx: BotContext) -> None:
    cfg = ctx.config

    async def start(client: Client, message: Message) -> None:
        user = message.from_user
        payload = message.command[1] if len(message.command) > 1 else None
        await ctx.db.upsert_user(
            user.id, user.first_name, user.username, source=payload, started=True
        )
        row = await ctx.db.get_user(user.id)

        if row and row.is_banned:
            await message.reply_text(texts.BANNED)
            return

        if row and row.completed:
            try:
                link = await link_for_returning_user(client, ctx, user.id, row.invite_link)
            except RPCError as exc:
                log.error("Could not get link for returning user %s: %s", user.id, exc)
                await message.reply_text(texts.CHECK_FAILED)
                return
            await message.reply_text(
                texts.reward_text(first_time=False),
                reply_markup=texts.reward_keyboard(link),
            )
            return

        await message.reply_text(
            texts.quest_text(cfg.required_channels),
            reply_markup=texts.quest_keyboard(cfg.required_channels),
            disable_web_page_preview=True,
        )
        if ctx.is_admin(user.id) and payload is None:
            await message.reply_text("🛠 You are an admin. Send /admin for the admin panel.")

    async def help_cmd(_: Client, message: Message) -> None:
        await message.reply_text(texts.USER_HELP)

    async def verify(client: Client, query: CallbackQuery) -> None:
        user = query.from_user

        wait = ctx.verify_cooldown_left(user.id)
        if wait > 0:
            await query.answer(f"⏳ Please wait {wait:.0f}s before checking again.")
            return

        try:
            result = await verify_user(client, ctx, user)
        except RPCError as exc:
            log.exception("Verification failed for %s", user.id)
            await query.answer(texts.CHECK_FAILED, show_alert=True)
            await ctx.notify_admins(
                client,
                f"⚠️ Verification error for user <code>{user.id}</code>: "
                f"<code>{type(exc).__name__}: {exc}</code>\nRun /check.",
                dedupe_key=f"verify-{type(exc).__name__}",
            )
            return

        if result.outcome is Outcome.BANNED:
            await query.answer(texts.BANNED, show_alert=True)
            return

        if result.outcome in (Outcome.COMPLETED, Outcome.ALREADY_DONE):
            first = result.outcome is Outcome.COMPLETED
            await query.answer("🎉 Verified!" if first else "✅ Already unlocked")
            await _edit(
                query,
                texts.reward_text(first_time=first),
                texts.reward_keyboard(result.link),
            )
            return

        if result.outcome is Outcome.CHECK_ERROR:
            await query.answer(texts.CHECK_FAILED, show_alert=True)
            await ctx.notify_admins(
                client,
                "⚠️ A membership check failed — the bot is probably not an admin "
                "in one of the required channels. Run /check.",
                dedupe_key="membership-check-failed",
            )
        else:  # MISSING
            missing = [
                ch.title for ch in cfg.required_channels if result.status.get(ch.key) is False
            ]
            await query.answer(
                "❌ You haven't joined: " + ", ".join(missing), show_alert=True
            )

        await _edit(
            query,
            texts.quest_text(cfg.required_channels, result.status),
            texts.quest_keyboard(cfg.required_channels, result.status),
        )

    app.add_handler(MessageHandler(start, filters.command("start") & filters.private))
    app.add_handler(MessageHandler(help_cmd, filters.command("help") & filters.private))
    app.add_handler(CallbackQueryHandler(verify, filters.regex(f"^{texts.CB_VERIFY}$")))


async def _edit(query: CallbackQuery, text: str, markup) -> None:
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except RPCError as exc:
        log.warning("Could not edit quest message: %s", exc)
        await query.message.reply_text(text, reply_markup=markup)
