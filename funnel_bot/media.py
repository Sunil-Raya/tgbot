"""Media (photo / video / GIF) support for the loop message."""

from __future__ import annotations

from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

MEDIA_TYPES = ("photo", "video", "animation")

# Telegram caption limit for regular bots.
CAPTION_LIMIT = 1024

_EXTENSIONS = {
    ".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".webp": "photo",
    ".mp4": "video", ".mov": "video", ".mkv": "video", ".webm": "video", ".m4v": "video",
    ".gif": "animation",
}


def guess_type(source: str) -> str | None:
    """Guess the media type from a file name or URL extension."""
    suffix = Path(source.split("?", 1)[0]).suffix.lower()
    return _EXTENSIONS.get(suffix)


def extract_media(message: Message | None) -> tuple[str, str] | None:
    """(media_type, file_id) of a photo / video / GIF message, else None."""
    if message is None:
        return None
    for media_type in ("animation", "video", "photo"):  # GIFs also carry .document
        media = getattr(message, media_type, None)
        if media is not None:
            return media_type, media.file_id
    return None


async def send_media(
    client: Client, chat_id: int, media_type: str, media: str, **kwargs
) -> Message:
    senders = {
        "photo": client.send_photo,
        "video": client.send_video,
        "animation": client.send_animation,
    }
    return await senders[media_type](chat_id, media, **kwargs)
