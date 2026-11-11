"""Background loop: every N seconds delete the previous promo message in the
private channel and post a fresh one with the "Share" deep-link button.
The post can carry a photo, video or GIF (text becomes its caption).

Design notes
------------
* Runs as one ``asyncio.Task`` on the same event loop as Pyrogram, so it never
  blocks update handling (all waits are ``await``-ed, never ``time.sleep``).
* The id of the last posted message is stored in SQLite, so after a restart
  the bot still deletes the message it posted before going down.
* Ticks are scheduled against a monotonic deadline, so the period stays at
  the configured interval and does not drift by the time a tick takes.
* ``poke()`` wakes the loop immediately (used by /loop now, /interval, ...).
* Every error is caught and logged; one failed tick never kills the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError

from . import texts
from .context import BotContext, Keys
from .media import CAPTION_LIMIT, MEDIA_TYPES, send_media

log = logging.getLogger(__name__)


class ChannelLoop:
    def __init__(self, client: Client, ctx: BotContext) -> None:
        self.client = client
        self.ctx = ctx
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.consecutive_errors = 0

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="channel-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def poke(self) -> None:
        """Run a tick right now instead of waiting for the next deadline."""
        self._wake.set()

    # ------------------------------------------------------------------ #
    # settings helpers
    # ------------------------------------------------------------------ #
    async def enabled(self) -> bool:
        return await self.ctx.db.get_bool(Keys.LOOP_ENABLED, self.ctx.config.loop_enabled_default)

    async def interval(self) -> int:
        value = await self.ctx.db.get_int(Keys.LOOP_INTERVAL, self.ctx.config.loop_interval_seconds)
        return max(10, value or self.ctx.config.loop_interval_seconds)

    async def text(self) -> str:
        return await self.ctx.db.get_setting(Keys.LOOP_TEXT, self.ctx.config.loop_text)

    # ------------------------------------------------------------------ #
    # main loop
    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        log.info("Channel loop started")
        loop = asyncio.get_running_loop()
        while True:
            delay: float | None = None
            try:
                if await self.enabled():
                    await self.tick()
                self.consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except FloodWait as exc:
                delay = float(exc.value) + 1
                log.warning("FloodWait in channel loop, sleeping %ss", delay)
            except Exception as exc:  # never let the loop die
                self.consecutive_errors += 1
                log.exception("Channel loop tick failed")
                if self.consecutive_errors == 3:
                    await self.ctx.notify_admins(
                        self.client,
                        "⚠️ The 1-minute channel loop failed 3 times in a row:\n"
                        f"<code>{type(exc).__name__}: {exc}</code>\n"
                        "Run /check to verify the bot's admin rights.",
                        dedupe_key="loop-failing",
                    )

            if delay is None:
                delay = await self.interval()
            deadline = loop.time() + delay
            self._wake.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.0, deadline - loop.time()))

    async def media(self) -> tuple[str, str, str | None] | None:
        """The media to attach: (type, file_id/path/url, env_source_to_cache).

        Priority: media set with /loopmedia  >  LOOP_MEDIA from .env  >  none.
        ``/loopmedia none`` stores type "none" = text only, even if .env has media.
        """
        db, cfg = self.ctx.db, self.ctx.config
        media_type = await db.get_setting(Keys.LOOP_MEDIA_TYPE)
        if media_type == "none":
            return None
        if media_type in MEDIA_TYPES:
            file_id = await db.get_setting(Keys.LOOP_MEDIA_FILE_ID)
            if file_id:
                return media_type, file_id, None
        if cfg.loop_media and cfg.loop_media_type:
            # Re-use the file_id from the first upload instead of uploading
            # the same file every minute.
            cached = await db.get_setting(Keys.LOOP_MEDIA_CACHE, "")
            source, _, file_id = cached.partition("\n")
            if source == cfg.loop_media and file_id:
                return cfg.loop_media_type, file_id, None
            return cfg.loop_media_type, cfg.loop_media, cfg.loop_media
        return None

    async def tick(self) -> None:
        """Delete the previous loop message, then post a new one."""
        await self.delete_previous()
        message = await self._post()
        await self.ctx.db.set_setting(Keys.LOOP_LAST_MESSAGE_ID, message.id)
        log.debug("Posted loop message %s", message.id)

    async def _post(self):
        chat_id = self.ctx.config.private_channel_id
        text = await self.text()
        common = dict(
            reply_markup=texts.share_keyboard(self.ctx.quest_deep_link),
            disable_notification=True,
        )
        media = await self.media()
        if media is not None:
            media_type, file, cache_source = media
            try:
                message = await send_media(
                    self.client, chat_id, media_type, file,
                    caption=text[:CAPTION_LIMIT], **common,
                )
            except FloodWait:
                raise
            except (RPCError, OSError, ValueError) as exc:
                # Broken file id / unreachable URL / missing file: don't stop
                # the loop, fall back to a text post and tell the admins.
                log.error("Loop media (%s) failed, posting text only: %s", media_type, exc)
                await self.ctx.db.set_setting(Keys.LOOP_MEDIA_CACHE, None)
                await self.ctx.notify_admins(
                    self.client,
                    f"⚠️ The loop {media_type} could not be sent, posting text only:\n"
                    f"<code>{type(exc).__name__}: {exc}</code>\n"
                    "Set a new one with /loopmedia (reply to a photo/video/GIF).",
                    dedupe_key="loop-media-failed",
                )
            else:
                if cache_source is not None:
                    sent = getattr(message, media_type, None)
                    if sent is not None:
                        await self.ctx.db.set_setting(
                            Keys.LOOP_MEDIA_CACHE, f"{cache_source}\n{sent.file_id}"
                        )
                return message
        return await self.client.send_message(chat_id, text, **common)

    async def delete_previous(self) -> None:
        last_id = await self.ctx.db.get_int(Keys.LOOP_LAST_MESSAGE_ID, None)
        if not last_id:
            return
        try:
            await self.client.delete_messages(self.ctx.config.private_channel_id, last_id)
        except FloodWait:
            raise  # keep the id so we retry after waiting
        except RPCError as exc:
            # Already deleted by someone, too old, etc. Nothing to retry.
            log.warning("Could not delete previous loop message %s: %s", last_id, exc)
        await self.ctx.db.set_setting(Keys.LOOP_LAST_MESSAGE_ID, None)
