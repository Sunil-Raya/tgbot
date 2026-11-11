"""Startup / on-demand self-diagnostics: is the bot an admin with the right
permissions in every channel it depends on?"""

from __future__ import annotations

import logging
from html import escape

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import RPCError

from .context import BotContext

log = logging.getLogger(__name__)

RIGHT_LABELS = {
    "can_invite_users": "Invite users / approve requests",
    "can_post_messages": "Post messages",
    "can_delete_messages": "Delete messages",
}


def _requirements(ctx: BotContext) -> list[tuple[str, int, set[str]]]:
    cfg = ctx.config
    reqs: dict[int, tuple[str, set[str]]] = {
        cfg.private_channel_id: (
            "Private channel",
            {"can_invite_users", "can_post_messages", "can_delete_messages"},
        ),
    }
    for ch in cfg.required_channels:
        # Being an admin (any rights) is what allows get_chat_member on channels.
        reqs[ch.chat_id] = (f"Required: {ch.title}", set())
    label, rights = reqs.get(cfg.announce_channel_id, ("Announcement channel", set()))
    reqs[cfg.announce_channel_id] = (label + " (announcements)", rights | {"can_post_messages"})
    return [(label, chat_id, rights) for chat_id, (label, rights) in reqs.items()]


async def run_checks(client: Client, ctx: BotContext) -> tuple[bool, str]:
    """Returns (all_ok, html_report)."""
    lines = ["🩺 <b>Configuration check</b>", ""]
    all_ok = True
    for label, chat_id, rights in _requirements(ctx):
        try:
            chat = await client.get_chat(chat_id)
            me = await client.get_chat_member(chat_id, ctx.bot_id)
        except RPCError as exc:
            all_ok = False
            lines.append(f"❌ {escape(label)} <code>{chat_id}</code>: {escape(str(exc))}")
            continue

        title = escape(chat.title or str(chat_id))
        if me.status == ChatMemberStatus.OWNER:
            lines.append(f"✅ {escape(label)} — {title}")
            continue
        if me.status != ChatMemberStatus.ADMINISTRATOR:
            all_ok = False
            lines.append(f"❌ {escape(label)} — {title}: bot is <b>not an admin</b>")
            continue

        missing = [r for r in sorted(rights) if not getattr(me.privileges, r, False)]
        if missing:
            all_ok = False
            names = ", ".join(RIGHT_LABELS.get(r, r) for r in missing)
            lines.append(f"⚠️ {escape(label)} — {title}: missing rights: {names}")
        else:
            lines.append(f"✅ {escape(label)} — {title}")

    lines += ["", "All good ✅" if all_ok else "Fix the items above, then run /check again."]
    report = "\n".join(lines)
    (log.info if all_ok else log.warning)("Config check: %s", "OK" if all_ok else "problems found")
    return all_ok, report
