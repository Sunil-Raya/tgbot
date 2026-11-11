import asyncio

import pytest

from funnel_bot.context import Keys
from funnel_bot.quest import Outcome, verify_user

from .conftest import MAIN, PRIVATE, SEC1, SEC2, make_config, tg_user

pytestmark = pytest.mark.asyncio


def join_all(client, uid=42):
    for chat in (SEC1, SEC2, MAIN):
        client.join(chat, uid)


async def test_missing_channels_are_reported(ctx, client):
    client.join(SEC1, 42)
    result = await verify_user(client, ctx, tg_user())
    assert result.outcome is Outcome.MISSING
    assert result.status == {"secondary_1": True, "secondary_2": False, "main": False}
    assert client.links_created == []
    row = await ctx.db.get_user(42)
    assert not row.completed and row.verify_attempts == 1


async def test_full_completion_gives_link_and_announces_once(ctx, client):
    join_all(client)
    result = await verify_user(client, ctx, tg_user())
    assert result.outcome is Outcome.COMPLETED
    assert result.link == client.links_created[0]

    announcements = [m for m in client.sent if m.chat_id == MAIN]
    assert len(announcements) == 1
    assert announcements[0].text == "🎉 User <b>Alice</b> just unlocked the private channel!"

    row = await ctx.db.get_user(42)
    assert row.completed and row.invite_link == result.link


async def test_completed_user_does_not_repeat_quest(ctx, client):
    join_all(client)
    first = await verify_user(client, ctx, tg_user())
    # User left the required channels afterwards and is in the private channel.
    client.members.clear()
    client.join(PRIVATE, 42)
    again = await verify_user(client, ctx, tg_user())
    assert again.outcome is Outcome.ALREADY_DONE
    assert again.link == first.link
    assert len([m for m in client.sent if m.chat_id == MAIN]) == 1


async def test_returning_user_not_in_channel_gets_fresh_unique_link(ctx, client):
    join_all(client)
    first = await verify_user(client, ctx, tg_user())
    again = await verify_user(client, ctx, tg_user())  # never joined PRIVATE
    assert again.outcome is Outcome.ALREADY_DONE
    assert again.link != first.link
    assert client.links_revoked == [first.link]


async def test_concurrent_clicks_announce_only_once(ctx, client):
    join_all(client)
    results = await asyncio.gather(*(verify_user(client, ctx, tg_user()) for _ in range(5)))
    outcomes = [r.outcome for r in results]
    assert outcomes.count(Outcome.COMPLETED) == 1
    assert len([m for m in client.sent if m.chat_id == MAIN]) == 1


async def test_check_error_when_bot_not_admin(ctx, client):
    join_all(client)
    client.broken_chats.add(SEC2)
    result = await verify_user(client, ctx, tg_user())
    assert result.outcome is Outcome.CHECK_ERROR
    assert result.status["secondary_2"] is None
    assert not (await ctx.db.get_user(42)).completed


async def test_banned_user_is_rejected(ctx, client):
    join_all(client)
    await ctx.db.set_banned(42, True)
    result = await verify_user(client, ctx, tg_user())
    assert result.outcome is Outcome.BANNED
    assert client.links_created == []


async def test_announcement_can_be_disabled(ctx, client):
    await ctx.db.set_bool(Keys.ANNOUNCE_ENABLED, False)
    join_all(client)
    result = await verify_user(client, ctx, tg_user())
    assert result.outcome is Outcome.COMPLETED
    assert [m for m in client.sent if m.chat_id == MAIN] == []


async def test_announcement_escapes_html(ctx, client):
    join_all(client)
    await verify_user(client, ctx, tg_user(first_name="<b>x</b>&"))
    ann = [m for m in client.sent if m.chat_id == MAIN][0]
    assert "&lt;b&gt;x&lt;/b&gt;&amp;" in ann.text


async def test_permanent_mode_reuses_one_link(tmp_path, db, client):
    from funnel_bot.context import BotContext

    ctx = BotContext(config=make_config(tmp_path, invite_link_mode="permanent"), db=db)
    ctx.bot_username = "TestFunnelBot"
    join_all(client, 1)
    join_all(client, 2)
    r1 = await verify_user(client, ctx, tg_user(1))
    r2 = await verify_user(client, ctx, tg_user(2))
    assert r1.link == r2.link
    assert len(client.links_created) == 1
