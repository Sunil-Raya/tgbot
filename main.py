"""Entry point: python main.py"""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from pyrogram import Client, idle
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from funnel_bot.checks import run_checks
from funnel_bot.config import ConfigError, load_config
from funnel_bot.context import BotContext
from funnel_bot.database import Database
from funnel_bot.handlers import register_all
from funnel_bot.scheduler import ChannelLoop

log = logging.getLogger("funnel_bot")

USER_COMMANDS = [
    BotCommand("start", "Start / show your quest"),
    BotCommand("help", "How it works"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("admin", "Admin panel"),
    BotCommand("stats", "Funnel statistics"),
    BotCommand("check", "Check bot permissions"),
    BotCommand("user", "Look up a user"),
    BotCommand("export", "Export users CSV"),
    BotCommand("reset", "Reset a user's quest"),
    BotCommand("ban", "Ban a user"),
    BotCommand("unban", "Unban a user"),
    BotCommand("loop", "Control the channel loop"),
    BotCommand("interval", "Set loop interval"),
    BotCommand("looptext", "Set loop text"),
    BotCommand("announce", "Toggle announcements"),
    BotCommand("broadcast", "Broadcast (reply to a message)"),
]


def setup_logging(data_dir) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file = RotatingFileHandler(
        data_dir / "bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[console, file])
    logging.getLogger("pyrogram").setLevel(logging.WARNING)


async def set_commands(app: Client, ctx: BotContext) -> None:
    try:
        await app.set_bot_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    except RPCError as exc:
        log.warning("Could not set user commands: %s", exc)
    for admin_id in ctx.config.admin_ids:
        try:
            await app.set_bot_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(admin_id))
        except RPCError as exc:  # admin has not started the bot yet
            log.warning("Could not set admin commands for %s: %s", admin_id, exc)


async def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}\nSee .env.example / README.md", file=sys.stderr)
        sys.exit(2)

    setup_logging(config.data_dir)

    db = Database(config.db_path)
    await db.connect()
    ctx = BotContext(config=config, db=db)

    app = Client(
        name="funnel_bot",
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        workdir=str(config.data_dir),   # session file lives next to the DB
        parse_mode=ParseMode.HTML,
        skip_updates=False,             # process join requests that arrived while offline
    )
    register_all(app, ctx)

    await app.start()
    try:
        me = await app.get_me()
        ctx.bot_id, ctx.bot_username = me.id, me.username
        log.info("Logged in as @%s (%s)", me.username, me.id)

        await set_commands(app, ctx)

        ok, report = await run_checks(app, ctx)
        await ctx.notify_admins(app, ("✅ Bot started.\n\n" if ok else "⚠️ Bot started with problems.\n\n") + report)

        ctx.loop = ChannelLoop(app, ctx)
        ctx.loop.start()

        await idle()  # wait for Ctrl+C / SIGTERM
    finally:
        log.info("Shutting down…")
        if ctx.loop:
            await ctx.loop.stop()
        for task in list(ctx.background_tasks):
            task.cancel()
        await app.stop()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
