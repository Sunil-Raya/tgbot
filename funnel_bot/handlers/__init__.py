from pyrogram import Client

from ..context import BotContext
from . import admin, join_requests, user


def register_all(app: Client, ctx: BotContext) -> None:
    join_requests.register(app, ctx)
    user.register(app, ctx)
    admin.register(app, ctx)
