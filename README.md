# Telegram Verification Funnel Bot

A Pyrogram + SQLite bot that:

1. **Auto-approves** every join request to your private channel.
2. **Posts a promo message every 1 minute** in that channel ("Share to 3 groups to unlock the channel for everyone!" + a **Share** button), **deleting the previous one first** so the channel never fills with spam.
3. The **Share** button deep-links to the bot (`t.me/<YourBot>?start=quest`), where the user gets a **quest**: join 2 secondary channels + 1 main channel, then tap **✅ Verify**.
4. **Verify** checks the database and then the Telegram API (`get_chat_member`) for all 3 channels, and sends the user an **invite link** to the private channel.
5. Right after a user unlocks it, the bot posts **"🎉 User [First Name] just unlocked the private channel!"** in the main/announcement channel.

Completed users are stored in SQLite, so they never have to repeat the quest.

---

## 1. The plan, step by step

| # | Step | Where in the code |
|---|------|-------------------|
| 1 | Load and validate all settings from `.env` (fail fast with a clear error) | `funnel_bot/config.py` |
| 2 | Open SQLite (WAL mode), create tables `users`, `join_requests`, `settings` | `funnel_bot/database.py` |
| 3 | Create the Pyrogram client and register handlers | `main.py`, `funnel_bot/handlers/` |
| 4 | Start, read the bot's own username (needed for the deep link) | `main.py` |
| 5 | Self-check: is the bot admin with the right permissions in every channel? Report to admins | `funnel_bot/checks.py` |
| 6 | Start the 1-minute loop as an `asyncio` task: delete last message → post new one → store its id | `funnel_bot/scheduler.py` |
| 7 | Join request to private channel → approve → log → optional welcome DM with "Start quest" | `funnel_bot/handlers/join_requests.py` |
| 8 | `/start quest` in DM → show 3 channel buttons + **Verify** (or the link, if already done) | `funnel_bot/handlers/user.py` |
| 9 | **Verify** → DB check → `get_chat_member` ×3 → issue invite link → mark completed → announce | `funnel_bot/quest.py`, `funnel_bot/rewards.py` |
| 10 | Admin commands, restricted by numeric user id | `funnel_bot/handlers/admin.py` |
| 11 | On Ctrl+C / SIGTERM: stop loop, cancel tasks, stop client, close DB | `main.py` |

---

## 2. Telegram setup (do this first)

1. Create a bot with **@BotFather**, copy the **BOT_TOKEN**.
2. Get **API_ID** and **API_HASH** at <https://my.telegram.org> → *API development tools*.
3. Get your own numeric user id (e.g. from **@userinfobot**) → put it in **ADMIN_IDS**.
4. Add the bot as **administrator** to all channels:

| Channel | Required admin rights |
|---|---|
| Private channel | **Invite users via link** (approve requests + create links), **Post messages**, **Delete messages** |
| Secondary channel 1 & 2 | Admin (any rights) – Telegram only lets admins see a channel's members |
| Main channel | Admin + **Post messages** (for the announcement) |

5. In the private channel, create an invite link with **"Request admin approval"** turned on and share that link. Every request is approved automatically by the bot.
6. Get each channel's numeric id (starts with `-100`): forward a post from the channel to **@userinfobot** / **@RawDataBot**, or open the channel in web.telegram.org — the URL contains the id (`#-100…`).
7. Start the bot once in DM yourself (so it can message you admin alerts).

After the bot starts, send **/check** in DM — it tells you exactly which permission is missing, if any.

---

## 3. Configuration (`.env`)

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `API_ID` | ✅ | From my.telegram.org |
| `API_HASH` | ✅ | From my.telegram.org |
| `BOT_TOKEN` | ✅ | From @BotFather |
| `ADMIN_IDS` | ✅ | Comma-separated numeric user ids allowed to use admin commands |
| `PRIVATE_CHANNEL_ID` | ✅ | Private channel (auto-accept + 1-minute loop) |
| `SECONDARY_CHANNEL_1_ID` / `_LINK` / `_TITLE` | ✅ / ✅ / optional | Required channel #1 |
| `SECONDARY_CHANNEL_2_ID` / `_LINK` / `_TITLE` | ✅ / ✅ / optional | Required channel #2 |
| `MAIN_CHANNEL_ID` / `_LINK` / `_TITLE` | ✅ / ✅ / optional | Required main broadcast channel #3 |
| `ANNOUNCE_CHANNEL_ID` | optional | Where unlock announcements go (default: main channel) |
| `INVITE_LINK_MODE` | optional | `unique` (default, single-use link per user) or `permanent` (one shared link) |
| `PERMANENT_INVITE_LINK` | optional | Link used in `permanent` mode (auto-created if empty) |
| `LOOP_INTERVAL_SECONDS` | optional | Default `60`, minimum `10` |
| `LOOP_ENABLED` | optional | Default `true` |
| `LOOP_TEXT` | optional | Default "Share to 3 groups to unlock the channel for everyone!" |
| `VERIFY_COOLDOWN_SECONDS` | optional | Anti-spam cooldown on the Verify button (default `5`) |
| `WELCOME_DM_ON_JOIN` | optional | DM approved joiners a "Start quest" button (default `true`) |
| `ANNOUNCE_ENABLED` | optional | Default `true` |
| `DATA_DIR` | optional | DB, session file and logs (default `data/`) |

---

## 4. Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit it
python main.py
```

Run it permanently with systemd, `pm2`, `screen`, or Docker. Data lives in `DATA_DIR`
(`funnel_bot.sqlite3`, `funnel_bot.session`, `bot.log`) — back that folder up.

Tests (no Telegram account needed, uses a fake client):

```bash
pip install -r requirements-dev.txt
pytest
```

---

## 5. Commands

**Users (DM):**

| Command | What it does |
|---|---|
| `/start` | Shows the quest (or your link again if you already completed it) |
| `/help` | How it works |

**Admins only** (checked against `ADMIN_IDS`; anyone else gets "⛔ admins only" in DM, is ignored elsewhere, and nothing runs):

| Command | What it does |
|---|---|
| `/admin` | Admin panel / command list |
| `/stats` | Join requests, starts, completions, conversion rate, 24h numbers |
| `/check` | Verifies the bot's admin rights in every channel |
| `/user <id\|@username>` | Shows one user's record |
| `/export` | Sends all users as a CSV file |
| `/reset <id>` | Resets a user's quest and revokes their unique link |
| `/ban <id>` | Blocks the user from the bot, revokes their link, removes & bans them from the private channel; their future join requests are declined |
| `/unban <id>` | Undoes `/ban` |
| `/loop on\|off\|now\|status` | Control the 1-minute loop (`off` also deletes the current loop message) |
| `/interval <seconds>` | Change the loop interval live (10–86400) |
| `/looptext <text>` / `/looptext reset` | Change the loop message text live |
| `/announce on\|off` | Toggle the public unlock announcements |
| `/broadcast` | Reply to any message with it → confirm → copied to every bot user (flood-safe; blocked users are tracked) |

Admins also get the admin command menu in Telegram's "/" list automatically.

---

## 6. Extra features included

- **Unique single-use invite links** (`member_limit=1`) so a reward link can't be shared publicly; if a completed user comes back and isn't in the channel, they get a fresh link and the old one is revoked.
- **Double-click safe**: per-user lock + atomic DB update → never two links or two announcements.
- **Verify cooldown** against button spam.
- **Clear feedback**: the quest message is updated with ✅/❌ per channel and an alert lists exactly which channels are missing.
- **Restart-safe loop**: the last loop message id is stored in SQLite, so after a restart the old message is still deleted; settings changed via commands survive restarts.
- **Drift-free scheduling** on the asyncio event loop; FloodWait and errors are handled and never kill the loop. Admins are alerted if it fails 3 times in a row.
- **Missed join requests are processed** after downtime (`skip_updates=False`).
- **Startup self-check** of all permissions, reported to admins via DM.
- **Admin alerts** (deduplicated) when approvals, checks or announcements fail.
- **Ban system** that also declines future join requests.
- **Broadcast** with confirmation, flood control and progress.
- **HTML-escaped** names in announcements (no formatting injection via first names).
- **Rotating log file** in `DATA_DIR/bot.log`.

---

## 7. Database schema

```sql
users(user_id PK, first_name, username, source, started_at, completed, completed_at,
      invite_link, verify_attempts, last_verify_at, is_banned, is_blocked,
      created_at, updated_at)
join_requests(id PK, user_id, chat_id, requested_at, approved, error)
settings(key PK, value)   -- loop_enabled, loop_interval, loop_text,
                          -- loop_last_message_id, announce_enabled, permanent_invite_link
```

---

## 8. Notes and limitations

- **Bots cannot check if someone shared a message to groups.** The "Share to 3 groups" text is the promo copy you asked for; what the bot actually verifies is membership in the 3 required channels.
- `get_chat_member` on a channel only works if the bot is an **admin** there — otherwise Verify answers "couldn't verify" and admins get an alert.
- The loop message in a channel is posted with `disable_notification=True`, so members aren't pinged every minute.
- Telegram ToS / spam rules still apply: very short loop intervals or aggressive broadcasting can get a bot limited.
