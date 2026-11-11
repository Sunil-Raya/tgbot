"""Configuration loaded from environment variables (or a `.env` file).

Every value the bot needs is defined here, validated once at startup, and
exposed as a frozen ``Config`` object so the rest of the code never touches
``os.environ`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or malformed."""


@dataclass(frozen=True)
class RequiredChannel:
    """A channel the user must join to complete the quest."""

    key: str          # stable identifier, e.g. "secondary_1"
    chat_id: int      # numeric id, e.g. -1001234567890
    link: str         # public/invite link shown on the button
    title: str        # button label


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str

    admin_ids: frozenset[int]

    private_channel_id: int
    announce_channel_id: int
    required_channels: tuple[RequiredChannel, ...]

    invite_link_mode: str                 # "unique" or "permanent"
    permanent_invite_link: str | None

    loop_interval_seconds: int
    loop_enabled_default: bool
    loop_text: str
    loop_media: str | None                # file path, URL or Telegram file_id
    loop_media_type: str | None           # "photo", "video" or "animation"

    verify_cooldown_seconds: int
    welcome_dm_on_join: bool
    announce_enabled_default: bool

    data_dir: Path
    db_path: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", self.data_dir / "funnel_bot.sqlite3")


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int | None = None) -> int:
    raw = _opt(name)
    if not raw:
        if default is None:
            raise ConfigError(f"Missing required environment variable: {name}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = _opt(name).lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true/false, got {raw!r}")


def _channel_id(name: str) -> int:
    value = _int(name)
    if value >= 0:
        raise ConfigError(
            f"{name} must be a channel id like -1001234567890 (negative), got {value}"
        )
    return value


def _admin_ids() -> frozenset[int]:
    raw = _req("ADMIN_IDS")
    ids: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_IDS contains a non-numeric id: {part!r}") from exc
    if not ids:
        raise ConfigError("ADMIN_IDS must contain at least one Telegram user id")
    return frozenset(ids)


def _required_channel(prefix: str, key: str, default_title: str) -> RequiredChannel:
    link = _req(f"{prefix}_LINK")
    if not link.startswith(("https://t.me/", "http://t.me/", "tg://")):
        raise ConfigError(f"{prefix}_LINK must be a t.me link, got {link!r}")
    return RequiredChannel(
        key=key,
        chat_id=_channel_id(f"{prefix}_ID"),
        link=link,
        title=_opt(f"{prefix}_TITLE", default_title),
    )


def _loop_media() -> tuple[str | None, str | None]:
    from .media import MEDIA_TYPES, guess_type

    source = _opt("LOOP_MEDIA") or None
    if source is None:
        return None, None
    media_type = _opt("LOOP_MEDIA_TYPE").lower() or guess_type(source)
    if media_type not in MEDIA_TYPES:
        raise ConfigError(
            "LOOP_MEDIA_TYPE must be photo, video or animation "
            "(could not guess it from LOOP_MEDIA)"
        )
    is_url = source.startswith(("http://", "https://"))
    looks_like_path = "/" in source or "\\" in source or guess_type(source) is not None
    if not is_url and looks_like_path and not Path(source).is_file():
        raise ConfigError(f"LOOP_MEDIA file not found: {source}")
    return source, media_type


def load_config() -> Config:
    """Read and validate all settings. Raises ``ConfigError`` on problems."""
    required = (
        _required_channel("SECONDARY_CHANNEL_1", "secondary_1", "📢 Channel 1"),
        _required_channel("SECONDARY_CHANNEL_2", "secondary_2", "📢 Channel 2"),
        _required_channel("MAIN_CHANNEL", "main", "⭐ Main Channel"),
    )
    if len({c.chat_id for c in required}) != len(required):
        raise ConfigError("The three required channels must have different ids")

    private_channel_id = _channel_id("PRIVATE_CHANNEL_ID")
    if private_channel_id in {c.chat_id for c in required}:
        raise ConfigError("PRIVATE_CHANNEL_ID must not be one of the required channels")

    main_channel_id = required[-1].chat_id
    announce_raw = _opt("ANNOUNCE_CHANNEL_ID")
    announce_channel_id = _channel_id("ANNOUNCE_CHANNEL_ID") if announce_raw else main_channel_id

    mode = _opt("INVITE_LINK_MODE", "unique").lower()
    if mode not in {"unique", "permanent"}:
        raise ConfigError("INVITE_LINK_MODE must be 'unique' or 'permanent'")

    interval = _int("LOOP_INTERVAL_SECONDS", 60)
    if interval < 10:
        raise ConfigError("LOOP_INTERVAL_SECONDS must be at least 10 (flood protection)")

    loop_media, loop_media_type = _loop_media()

    return Config(
        api_id=_int("API_ID"),
        api_hash=_req("API_HASH"),
        bot_token=_req("BOT_TOKEN"),
        admin_ids=_admin_ids(),
        private_channel_id=private_channel_id,
        announce_channel_id=announce_channel_id,
        required_channels=required,
        invite_link_mode=mode,
        permanent_invite_link=_opt("PERMANENT_INVITE_LINK") or None,
        loop_interval_seconds=interval,
        loop_enabled_default=_bool("LOOP_ENABLED", True),
        loop_text=_opt(
            "LOOP_TEXT", "Share to 3 groups to unlock the channel for everyone!"
        ),
        loop_media=loop_media,
        loop_media_type=loop_media_type,
        verify_cooldown_seconds=_int("VERIFY_COOLDOWN_SECONDS", 5),
        welcome_dm_on_join=_bool("WELCOME_DM_ON_JOIN", True),
        announce_enabled_default=_bool("ANNOUNCE_ENABLED", True),
        data_dir=Path(_opt("DATA_DIR", "data")).resolve(),
    )
