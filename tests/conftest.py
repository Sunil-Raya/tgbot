from __future__ import annotations

import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import ChatAdminRequired, UserNotParticipant

from funnel_bot.config import Config, RequiredChannel
from funnel_bot.context import BotContext
from funnel_bot.database import Database

PRIVATE = -1000000000001
SEC1 = -1000000000002
SEC2 = -1000000000003
MAIN = -1000000000004
ADMIN = 111


def make_config(tmp_path: Path, **overrides) -> Config:
    values = dict(
        api_id=1,
        api_hash="x",
        bot_token="1:x",
        admin_ids=frozenset({ADMIN}),
        private_channel_id=PRIVATE,
        announce_channel_id=MAIN,
        required_channels=(
            RequiredChannel("secondary_1", SEC1, "https://t.me/sec1", "Sec 1"),
            RequiredChannel("secondary_2", SEC2, "https://t.me/sec2", "Sec 2"),
            RequiredChannel("main", MAIN, "https://t.me/main", "Main"),
        ),
        invite_link_mode="unique",
        permanent_invite_link=None,
        loop_interval_seconds=60,
        loop_enabled_default=True,
        loop_text="Share to 3 groups to unlock the channel for everyone!",
        verify_cooldown_seconds=0,
        welcome_dm_on_join=True,
        announce_enabled_default=True,
        data_dir=tmp_path,
    )
    values.update(overrides)
    return Config(**values)


class FakeClient:
    """Just enough of pyrogram.Client for the bot's logic."""

    def __init__(self) -> None:
        self.members: dict[int, set[int]] = {}       # chat_id -> user ids
        self.broken_chats: set[int] = set()          # get_chat_member raises
        self.sent: list[SimpleNamespace] = []
        self.deleted: list[tuple[int, int]] = []
        self.links_created: list[str] = []
        self.links_revoked: list[str] = []
        self._ids = itertools.count(100)

    def join(self, chat_id: int, user_id: int) -> None:
        self.members.setdefault(chat_id, set()).add(user_id)

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.broken_chats:
            raise ChatAdminRequired()
        if user_id in self.members.get(chat_id, set()):
            return SimpleNamespace(status=ChatMemberStatus.MEMBER, is_member=True)
        raise UserNotParticipant()

    async def create_chat_invite_link(self, chat_id, name=None, member_limit=None, **_):
        link = f"https://t.me/+link{next(self._ids)}"
        self.links_created.append(link)
        return SimpleNamespace(invite_link=link)

    async def revoke_chat_invite_link(self, chat_id, invite_link):
        self.links_revoked.append(invite_link)

    async def send_message(self, chat_id, text, **kwargs):
        msg = SimpleNamespace(id=next(self._ids), chat_id=chat_id, text=text, kwargs=kwargs)
        self.sent.append(msg)
        return msg

    async def delete_messages(self, chat_id, message_ids):
        self.deleted.append((chat_id, message_ids))
        return 1


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def client():
    return FakeClient()


@pytest_asyncio.fixture
async def ctx(tmp_path, db):
    c = BotContext(config=make_config(tmp_path), db=db)
    c.bot_id, c.bot_username = 999, "TestFunnelBot"
    return c


def tg_user(user_id: int = 42, first_name: str = "Alice", username: str | None = "alice"):
    return SimpleNamespace(id=user_id, first_name=first_name, username=username)
