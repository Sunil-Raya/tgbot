"""Admin-only commands. Access is restricted by numeric Telegram user id
(ADMIN_IDS). Non-admins who try them get a refusal and nothing happens."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from html import escape

from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    RPCError,
    UserDeactivated,
    UserIsBlocked,
)
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import texts
from ..checks import run_checks
from ..context import BotContext, Keys
from ..database import UserRow
from ..rewards import revoke_link

log = logging.getLogger(__name__)

ADMIN_HELP = """🛠 <b>Admin panel</b>

<b>Monitoring</b>
/stats — funnel statistics
/check — verify the bot's rights in every channel
/user &lt;id|@username&gt; — show a user's record
/export — download all users as CSV

<b>Users</b>
/reset &lt;id&gt; — reset a user's quest (revokes their unique link)
/ban &lt;id&gt; — block from bot + remove from private channel
/unban &lt;id&gt; — undo /ban

<b>Channel loop</b>
/loop on|off|now|status — control the promo loop
/interval &lt;seconds&gt; — change the loop interval (min 10)
/looptext &lt;text&gt; | reset — change the loop message text

<b>Other</b>
/announce on|off — toggle public unlock announcements
/broadcast — reply to any message to send it to all bot users
"""

ADMIN_COMMANDS = [
    "admin", "panel", "stats", "check", "user", "export", "reset", "ban", "unban",
    "loop", "interval", "looptext", "announce", "broadcast",
]


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _user_card(row: UserRow) -> str:
    uname = f"@{escape(row.username)}" if row.username else "—"
    return (
        f"👤 <b>{escape(row.first_name or 'Unknown')}</b> ({uname})\n"
        f"ID: <code>{row.user_id}</code>\n"
        f"Started bot: {_fmt_ts(row.started_at)}  (source: {escape(row.source or '—')})\n"
        f"Quest completed: {'✅ ' + _fmt_ts(row.completed_at) if row.completed else '❌'}\n"
        f"Verify attempts: {row.verify_attempts}\n"
        f"Invite link: {escape(row.invite_link or '—')}\n"
        f"Banned: {'yes' if row.is_banned else 'no'} · Blocked bot: {'yes' if row.is_blocked else 'no'}"
    )


def _parse_user_id(message: Message) -> int | None:
    if len(message.command) < 2:
        return None
    try:
        return int(message.command[1])
    except ValueError:
        return None


def register(app: Client, ctx: BotContext) -> None:
    cfg = ctx.config
    db = ctx.db
    is_admin = filters.user(list(cfg.admin_ids))

    def cmd(names: str | list[str]):
        return filters.command(names) & is_admin

    # ------------------------------------------------------------------ #
    async def panel(_: Client, m: Message) -> None:
        await m.reply_text(ADMIN_HELP)

    async def stats(_: Client, m: Message) -> None:
        s = await db.stats()
        rate = (s["completed_total"] / s["users_started"] * 100) if s["users_started"] else 0
        loop_on = await db.get_bool(Keys.LOOP_ENABLED, cfg.loop_enabled_default)
        ann_on = await db.get_bool(Keys.ANNOUNCE_ENABLED, cfg.announce_enabled_default)
        await m.reply_text(
            "📊 <b>Funnel stats</b>\n\n"
            f"Join requests approved: <b>{s['join_approved_total']}</b> "
            f"(24h: {s['join_approved_24h']}, failed/declined: {s['join_failed_total']})\n"
            f"Users known: <b>{s['users_total']}</b>\n"
            f"Started bot: <b>{s['users_started']}</b> (24h: {s['started_24h']})\n"
            f"Quest completed: <b>{s['completed_total']}</b> (24h: {s['completed_24h']})\n"
            f"Conversion (started → completed): <b>{rate:.1f}%</b>\n"
            f"Banned: {s['banned']} · Blocked the bot: {s['blocked']}\n\n"
            f"Loop: {'🟢 on' if loop_on else '🔴 off'} · "
            f"Announcements: {'🟢 on' if ann_on else '🔴 off'}"
        )

    async def check(client: Client, m: Message) -> None:
        _, report = await run_checks(client, ctx)
        await m.reply_text(report)

    async def user_info(_: Client, m: Message) -> None:
        if len(m.command) < 2:
            await m.reply_text("Usage: /user &lt;id|@username&gt;")
            return
        arg = m.command[1]
        row = (
            await db.find_user_by_username(arg)
            if not arg.lstrip("-").isdigit()
            else await db.get_user(int(arg))
        )
        await m.reply_text(_user_card(row) if row else "User not found in the database.")

    async def export(client: Client, m: Message) -> None:
        rows = await db.all_users()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "user_id", "first_name", "username", "source", "started_at", "completed",
            "completed_at", "invite_link", "verify_attempts", "is_banned", "is_blocked",
        ])
        for r in rows:
            writer.writerow([
                r.user_id, r.first_name or "", r.username or "", r.source or "",
                _fmt_ts(r.started_at), int(r.completed), _fmt_ts(r.completed_at),
                r.invite_link or "", r.verify_attempts, int(r.is_banned), int(r.is_blocked),
            ])
        data = io.BytesIO(buf.getvalue().encode("utf-8"))
        data.name = f"users_{datetime.now(timezone.utc):%Y%m%d_%H%M}.csv"
        await client.send_document(m.chat.id, data, caption=f"👥 {len(rows)} users")

    async def reset(client: Client, m: Message) -> None:
        uid = _parse_user_id(m)
        if uid is None:
            await m.reply_text("Usage: /reset &lt;user_id&gt;")
            return
        row = await db.get_user(uid)
        if not row:
            await m.reply_text("User not found.")
            return
        await revoke_link(client, ctx, row.invite_link)
        await db.reset_user(uid)
        await m.reply_text(f"♻️ Quest reset for <code>{uid}</code>. They must complete it again.")

    async def ban(client: Client, m: Message) -> None:
        uid = _parse_user_id(m)
        if uid is None:
            await m.reply_text("Usage: /ban &lt;user_id&gt;")
            return
        if ctx.is_admin(uid):
            await m.reply_text("You can't ban an admin.")
            return
        row = await db.get_user(uid)
        await db.set_banned(uid, True)
        if row:
            await revoke_link(client, ctx, row.invite_link)
        note = ""
        try:
            await client.ban_chat_member(cfg.private_channel_id, uid)
        except RPCError as exc:
            note = f"\n⚠️ Could not remove from private channel: <code>{escape(str(exc))}</code>"
        await m.reply_text(f"🚫 <code>{uid}</code> banned.{note}")

    async def unban(client: Client, m: Message) -> None:
        uid = _parse_user_id(m)
        if uid is None:
            await m.reply_text("Usage: /unban &lt;user_id&gt;")
            return
        await db.set_banned(uid, False)
        note = ""
        try:
            await client.unban_chat_member(cfg.private_channel_id, uid)
        except RPCError as exc:
            note = f"\n⚠️ Could not unban in private channel: <code>{escape(str(exc))}</code>"
        await m.reply_text(f"✅ <code>{uid}</code> unbanned.{note}")

    async def loop_cmd(_: Client, m: Message) -> None:
        sub = m.command[1].lower() if len(m.command) > 1 else "status"
        loop = ctx.loop
        if loop is None:
            await m.reply_text("Loop is not initialised yet.")
            return
        if sub == "on":
            await db.set_bool(Keys.LOOP_ENABLED, True)
            loop.poke()
            await m.reply_text("🟢 Channel loop enabled (posting now).")
        elif sub == "off":
            await db.set_bool(Keys.LOOP_ENABLED, False)
            try:
                await loop.delete_previous()
            except RPCError as exc:
                log.warning("Could not delete loop message on /loop off: %s", exc)
            await m.reply_text("🔴 Channel loop disabled and last message removed.")
        elif sub == "now":
            if not await loop.enabled():
                await m.reply_text("Loop is off. Use /loop on first.")
                return
            loop.poke()
            await m.reply_text("⏩ Posting a fresh loop message now.")
        else:
            enabled = await loop.enabled()
            last = await db.get_setting(Keys.LOOP_LAST_MESSAGE_ID, "—")
            await m.reply_text(
                "🔁 <b>Channel loop</b>\n"
                f"Enabled: {'🟢 yes' if enabled else '🔴 no'}\n"
                f"Task running: {'yes' if loop.running else 'NO ⚠️'}\n"
                f"Interval: {await loop.interval()}s\n"
                f"Last message id: {last}\n"
                f"Text: {escape(await loop.text())}"
            )

    async def interval(_: Client, m: Message) -> None:
        try:
            seconds = int(m.command[1])
        except (IndexError, ValueError):
            await m.reply_text("Usage: /interval &lt;seconds&gt;  (10 – 86400)")
            return
        if not 10 <= seconds <= 86_400:
            await m.reply_text("Interval must be between 10 and 86400 seconds.")
            return
        await db.set_setting(Keys.LOOP_INTERVAL, seconds)
        if ctx.loop:
            ctx.loop.poke()
        await m.reply_text(f"⏱ Loop interval set to {seconds}s.")

    async def looptext(_: Client, m: Message) -> None:
        text = m.text.split(maxsplit=1)[1].strip() if len(m.text.split(maxsplit=1)) > 1 else ""
        if not text:
            await m.reply_text("Usage: /looptext &lt;new text&gt;  or  /looptext reset")
            return
        if text.lower() == "reset":
            await db.set_setting(Keys.LOOP_TEXT, None)
            await m.reply_text("Loop text reset to default.")
        else:
            await db.set_setting(Keys.LOOP_TEXT, text)
            await m.reply_text("✏️ Loop text updated. It will be used from the next post.")

    async def announce(_: Client, m: Message) -> None:
        sub = m.command[1].lower() if len(m.command) > 1 else ""
        if sub not in {"on", "off"}:
            on = await db.get_bool(Keys.ANNOUNCE_ENABLED, cfg.announce_enabled_default)
            await m.reply_text(f"Announcements are {'on' if on else 'off'}. Use /announce on|off.")
            return
        await db.set_bool(Keys.ANNOUNCE_ENABLED, sub == "on")
        await m.reply_text(f"📣 Announcements turned {sub}.")

    # ------------------------------------------------------------------ #
    # broadcast (with confirmation step)
    # ------------------------------------------------------------------ #
    async def broadcast(_: Client, m: Message) -> None:
        src = m.reply_to_message
        if src is None:
            await m.reply_text("Reply to the message you want to broadcast with /broadcast.")
            return
        count = len(await db.broadcast_targets())
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"✅ Send to {count} users", callback_data=f"bc:go:{src.chat.id}:{src.id}"
            ),
            InlineKeyboardButton("❌ Cancel", callback_data="bc:cancel"),
        ]])
        await m.reply_text("📢 Broadcast this message?", reply_markup=kb)

    async def broadcast_cb(client: Client, q: CallbackQuery) -> None:
        parts = q.data.split(":")
        if parts[1] == "cancel":
            await q.message.edit_text("Broadcast cancelled.")
            return
        if ctx.broadcast_running:
            await q.answer("A broadcast is already running.", show_alert=True)
            return
        from_chat, msg_id = int(parts[2]), int(parts[3])
        ctx.broadcast_running = True
        await q.answer("Broadcast started")
        await q.message.edit_text("📤 Broadcasting…")
        ctx.spawn(_run_broadcast(client, ctx, q.message, from_chat, msg_id))

    async def refuse(_: Client, m: Message) -> None:
        await m.reply_text(texts.ADMIN_ONLY)

    async def refuse_cb(_: Client, q: CallbackQuery) -> None:
        await q.answer(texts.ADMIN_ONLY, show_alert=True)

    handlers = [
        (panel, ["admin", "panel"]),
        (stats, "stats"),
        (check, "check"),
        (user_info, "user"),
        (export, "export"),
        (reset, "reset"),
        (ban, "ban"),
        (unban, "unban"),
        (loop_cmd, "loop"),
        (interval, "interval"),
        (looptext, "looptext"),
        (announce, "announce"),
        (broadcast, "broadcast"),
    ]
    for func, names in handlers:
        app.add_handler(MessageHandler(func, cmd(names)))
    app.add_handler(CallbackQueryHandler(broadcast_cb, filters.regex(r"^bc:") & is_admin))

    # Anyone else: polite refusal (only in DMs, to stay silent in groups).
    app.add_handler(
        MessageHandler(refuse, filters.command(ADMIN_COMMANDS) & filters.private & ~is_admin)
    )
    app.add_handler(CallbackQueryHandler(refuse_cb, filters.regex(r"^bc:") & ~is_admin))


async def _run_broadcast(
    client: Client, ctx: BotContext, status_msg: Message, from_chat: int, msg_id: int
) -> None:
    sent = blocked = failed = 0
    try:
        targets = await ctx.db.broadcast_targets()
        for i, uid in enumerate(targets, start=1):
            for attempt in range(2):
                try:
                    await client.copy_message(uid, from_chat, msg_id)
                    sent += 1
                    break
                except FloodWait as exc:
                    await asyncio.sleep(float(exc.value) + 1)
                    if attempt == 1:
                        failed += 1
                except (UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid):
                    blocked += 1
                    await ctx.db.set_blocked(uid, True)
                    break
                except RPCError as exc:
                    failed += 1
                    log.warning("Broadcast to %s failed: %s", uid, exc)
                    break
            await asyncio.sleep(0.05)  # ~20 msgs/s, below Telegram's 30/s bot limit
            if i % 200 == 0:
                try:
                    await status_msg.edit_text(f"📤 Broadcasting… {i}/{len(targets)}")
                except RPCError:
                    pass
        await status_msg.edit_text(
            "✅ <b>Broadcast finished</b>\n"
            f"Sent: {sent}\nBlocked/deleted accounts: {blocked}\nFailed: {failed}"
        )
    except Exception:
        log.exception("Broadcast crashed")
        try:
            await status_msg.edit_text(
                f"❌ Broadcast stopped by an error. Sent: {sent}, blocked: {blocked}, failed: {failed}"
            )
        except RPCError:
            pass
    finally:
        ctx.broadcast_running = False
