"""Channel-membership checks via ``get_chat_member``."""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait, RPCError, UserNotParticipant

from .config import RequiredChannel

log = logging.getLogger(__name__)

JOINED_STATUSES = {
    ChatMemberStatus.OWNER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


async def is_member(client: Client, chat_id: int, user_id: int) -> bool | None:
    """Return True/False for joined/not joined, or None if the check itself failed
    (bot is not an admin there, channel id wrong, Telegram error, ...)."""
    for attempt in range(2):
        try:
            member = await client.get_chat_member(chat_id, user_id)
        except UserNotParticipant:
            return False
        except FloodWait as exc:
            if attempt == 0 and isinstance(exc.value, int) and exc.value <= 30:
                await asyncio.sleep(exc.value)
                continue
            log.warning("FloodWait while checking %s in %s: %s", user_id, chat_id, exc)
            return None
        except RPCError as exc:
            log.error("Membership check failed for user %s in %s: %s", user_id, chat_id, exc)
            return None

        if member.status in JOINED_STATUSES:
            return True
        if member.status == ChatMemberStatus.RESTRICTED:
            # Restricted users may or may not still be in the chat.
            return bool(member.is_member)
        return False  # LEFT / BANNED
    return None


async def check_channels(
    client: Client, channels: tuple[RequiredChannel, ...], user_id: int
) -> dict[str, bool | None]:
    """Check all required channels concurrently. Keys are ``RequiredChannel.key``."""
    results = await asyncio.gather(
        *(is_member(client, ch.chat_id, user_id) for ch in channels)
    )
    return {ch.key: res for ch, res in zip(channels, results)}
