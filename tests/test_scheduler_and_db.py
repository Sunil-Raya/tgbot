import asyncio

import pytest

from funnel_bot.context import Keys
from funnel_bot.scheduler import ChannelLoop

from .conftest import PRIVATE

pytestmark = pytest.mark.asyncio


async def test_tick_deletes_previous_before_posting(ctx, client):
    loop = ChannelLoop(client, ctx)
    await loop.tick()
    first = client.sent[-1]
    assert first.chat_id == PRIVATE
    assert first.text == "Share to 3 groups to unlock the channel for everyone!"
    button = first.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "Share"
    assert button.url == "https://t.me/TestFunnelBot?start=quest"
    assert client.deleted == []

    await loop.tick()
    assert client.deleted == [(PRIVATE, first.id)]
    assert await ctx.db.get_int(Keys.LOOP_LAST_MESSAGE_ID, None) == client.sent[-1].id


async def test_last_message_id_survives_restart(ctx, client):
    await ChannelLoop(client, ctx).tick()
    posted = client.sent[-1].id
    # A brand-new loop object (as after a restart) still deletes the old post.
    await ChannelLoop(client, ctx).tick()
    assert client.deleted == [(PRIVATE, posted)]


async def test_background_loop_runs_and_respects_disable(ctx, client):
    await ctx.db.set_setting(Keys.LOOP_INTERVAL, 10)
    loop = ChannelLoop(client, ctx)
    loop.start()
    await asyncio.sleep(0.05)
    assert len(client.sent) == 1          # first tick is immediate
    loop.poke()
    await asyncio.sleep(0.05)
    assert len(client.sent) == 2 and len(client.deleted) == 1

    await ctx.db.set_bool(Keys.LOOP_ENABLED, False)
    loop.poke()
    await asyncio.sleep(0.05)
    assert len(client.sent) == 2          # disabled -> nothing posted
    await loop.stop()
    assert not loop.running


async def test_loop_survives_errors(ctx, client):
    calls = {"n": 0}
    original = client.send_message

    async def flaky(chat_id, text, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network down")
        return await original(chat_id, text, **kw)

    client.send_message = flaky
    loop = ChannelLoop(client, ctx)
    loop.start()
    await asyncio.sleep(0.05)
    loop.poke()
    await asyncio.sleep(0.05)
    assert loop.running and len(client.sent) == 1
    await loop.stop()


async def test_upsert_keeps_first_source(db):
    await db.upsert_user(1, "A", "a", source="quest", started=True)
    await db.upsert_user(1, "A2", "a2", source="other", started=True)
    row = await db.get_user(1)
    assert row.source == "quest" and row.first_name == "A2"


async def test_mark_completed_is_atomic(db):
    await db.upsert_user(1, "A", None, started=True)
    assert await db.mark_completed(1, "l1") is True
    assert await db.mark_completed(1, "l2") is False
    assert (await db.get_user(1)).invite_link == "l1"
    assert await db.reset_user(1)
    assert not (await db.get_user(1)).completed


async def test_broadcast_targets_and_stats(db):
    await db.upsert_user(1, "A", None, started=True)
    await db.upsert_user(2, "B", None, started=True)
    await db.upsert_user(3, "C", None)               # only sent a join request
    await db.set_banned(2, True)
    await db.log_join_request(3, PRIVATE, True)
    assert await db.broadcast_targets() == [1]
    await db.set_blocked(1, True)
    assert await db.broadcast_targets() == []
    s = await db.stats()
    assert s["users_total"] == 3 and s["users_started"] == 2
    assert s["banned"] == 1 and s["blocked"] == 1 and s["join_approved_total"] == 1
    assert (await db.find_user_by_username("@nobody")) is None
