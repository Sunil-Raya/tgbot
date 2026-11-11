import pytest

from funnel_bot.config import ConfigError, _loop_media
from funnel_bot.context import BotContext, Keys
from funnel_bot.media import guess_type
from funnel_bot.scheduler import ChannelLoop

from .conftest import ADMIN, PRIVATE, make_config



def loop_with(tmp_path, db, client, **cfg):
    ctx = BotContext(config=make_config(tmp_path, **cfg), db=db)
    ctx.bot_username = "TestFunnelBot"
    return ChannelLoop(client, ctx), ctx


async def test_env_media_uploaded_once_then_file_id_reused(tmp_path, db, client):
    loop, _ = loop_with(tmp_path, db, client, loop_media="promo.mp4", loop_media_type="video")
    await loop.tick()
    first = client.sent[-1]
    assert first.media_type == "video" and first.media == "promo.mp4"
    assert first.caption == "Share to 3 groups to unlock the channel for everyone!"
    assert first.kwargs["reply_markup"].inline_keyboard[0][0].text == "Share"

    await loop.tick()
    second = client.sent[-1]
    assert second.media == first.video.file_id          # cached, no re-upload
    assert client.deleted == [(PRIVATE, first.id)]       # old one still deleted


async def test_admin_media_overrides_env_and_none_disables(tmp_path, db, client):
    loop, ctx = loop_with(tmp_path, db, client, loop_media="promo.mp4", loop_media_type="video")
    await db.set_setting(Keys.LOOP_MEDIA_TYPE, "photo")
    await db.set_setting(Keys.LOOP_MEDIA_FILE_ID, "PHOTO123")
    await loop.tick()
    assert client.sent[-1].media_type == "photo" and client.sent[-1].media == "PHOTO123"

    await db.set_setting(Keys.LOOP_MEDIA_TYPE, "none")
    await loop.tick()
    assert client.sent[-1].text == ctx.config.loop_text  # plain text message


async def test_broken_media_falls_back_to_text_and_alerts(tmp_path, db, client):
    loop, ctx = loop_with(tmp_path, db, client)
    await db.set_setting(Keys.LOOP_MEDIA_TYPE, "animation")
    await db.set_setting(Keys.LOOP_MEDIA_FILE_ID, "BROKEN")
    client.bad_media.add("BROKEN")
    await loop.tick()
    posted = [m for m in client.sent if m.chat_id == PRIVATE]
    assert len(posted) == 1 and posted[0].text == ctx.config.loop_text
    assert any(m.chat_id == ADMIN and "could not be sent" in m.text for m in client.sent)


async def test_long_text_is_cut_to_caption_limit(tmp_path, db, client):
    loop, _ = loop_with(tmp_path, db, client)
    await db.set_setting(Keys.LOOP_TEXT, "x" * 2000)
    await db.set_setting(Keys.LOOP_MEDIA_TYPE, "photo")
    await db.set_setting(Keys.LOOP_MEDIA_FILE_ID, "P")
    await loop.tick()
    assert len(client.sent[-1].caption) == 1024


def test_guess_type():
    assert guess_type("a/b/promo.JPG") == "photo"
    assert guess_type("https://x.com/v.mp4?sig=1") == "video"
    assert guess_type("fun.gif") == "animation"
    assert guess_type("AgACAgQAAxkBAAIB") is None


def test_env_media_validation(tmp_path, monkeypatch):
    img = tmp_path / "banner.png"
    img.write_bytes(b"x")
    monkeypatch.setenv("LOOP_MEDIA", str(img))
    monkeypatch.delenv("LOOP_MEDIA_TYPE", raising=False)
    assert _loop_media() == (str(img), "photo")

    monkeypatch.setenv("LOOP_MEDIA", str(tmp_path / "missing.mp4"))
    with pytest.raises(ConfigError):
        _loop_media()

    monkeypatch.setenv("LOOP_MEDIA", "AgACAgQAAxkBAAIB")      # a bare file_id
    with pytest.raises(ConfigError):                           # type required
        _loop_media()
    monkeypatch.setenv("LOOP_MEDIA_TYPE", "photo")
    assert _loop_media() == ("AgACAgQAAxkBAAIB", "photo")
