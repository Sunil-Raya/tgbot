"""User-facing texts and inline keyboards (HTML parse mode)."""

from __future__ import annotations

from html import escape
from typing import Mapping

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import RequiredChannel

CB_VERIFY = "quest:verify"

STATUS_ICON = {True: "✅", False: "❌", None: "⚠️"}


def share_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    """Keyboard for the 1-minute loop message in the private channel."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("Share", url=deep_link)]])


def quest_text(
    channels: tuple[RequiredChannel, ...],
    status: Mapping[str, bool | None] | None = None,
) -> str:
    lines = [
        "🔐 <b>Unlock the private channel</b>",
        "",
        "Complete this quick quest to get your access link:",
        "",
    ]
    for i, ch in enumerate(channels, start=1):
        icon = STATUS_ICON[status.get(ch.key)] if status else "▫️"
        lines.append(f"{icon} {i}. Join <b>{escape(ch.title)}</b>")
    lines += ["", "When you have joined all of them, tap <b>✅ Verify</b>."]
    if status and not all(status.get(ch.key) for ch in channels):
        lines += ["", "<i>❌ = not joined yet. Join them and tap Verify again.</i>"]
    return "\n".join(lines)


def quest_keyboard(
    channels: tuple[RequiredChannel, ...],
    status: Mapping[str, bool | None] | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        prefix = f"{STATUS_ICON[status.get(ch.key)]} " if status else ""
        rows.append([InlineKeyboardButton(f"{prefix}{ch.title}", url=ch.link)])
    rows.append([InlineKeyboardButton("✅ Verify", callback_data=CB_VERIFY)])
    return InlineKeyboardMarkup(rows)


def reward_text(first_time: bool) -> str:
    head = "🎉 <b>Quest complete!</b>" if first_time else "✅ <b>You already unlocked it!</b>"
    return (
        f"{head}\n\n"
        "Here is your access link to the private channel.\n"
        "<i>Stay subscribed to the required channels.</i>"
    )


def reward_keyboard(invite_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔓 Open private channel", url=invite_link)]]
    )


def announcement_text(first_name: str | None) -> str:
    name = escape(first_name or "Someone")
    return f"🎉 User <b>{name}</b> just unlocked the private channel!"


def announcement_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔓 Unlock it too", url=deep_link)]]
    )


def join_welcome_text(first_name: str | None) -> str:
    return (
        f"👋 Hi {escape(first_name or 'there')}, your request to join was approved!\n\n"
        "Complete a quick quest to unlock the channel for everyone 👇"
    )


def start_quest_keyboard(deep_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start quest", url=deep_link)]])


USER_HELP = (
    "ℹ️ <b>How it works</b>\n\n"
    "1. Send /start to see your quest.\n"
    "2. Join every channel in the list.\n"
    "3. Tap <b>✅ Verify</b> to receive your private-channel link.\n\n"
    "Already done? /start shows your link again."
)

BANNED = "🚫 You are not allowed to use this bot."
CHECK_FAILED = (
    "⚠️ I couldn't verify one of the channels right now. "
    "The admins have been notified — please try again in a few minutes."
)
ADMIN_ONLY = "⛔ This command is only available to bot admins."
