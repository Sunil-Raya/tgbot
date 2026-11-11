# Graph Report - tgbot  (2026-11-11)

## Corpus Check
- 22 files · ~10,746 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: .example 1, (none) 1, .ini 1)

## Summary
- 289 nodes · 739 edges · 11 communities (9 shown, 2 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 112 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `91484ba8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- admin.py
- Database
- config.py
- register
- texts.py
- ChannelLoop
- BotContext
- verify_user
- FakeClient
- Telegram Verification Funnel Bot

## God Nodes (most connected - your core abstractions)
1. `BotContext` - 42 edges
2. `Database` - 29 edges
3. `register()` - 26 edges
4. `verify_user()` - 26 edges
5. `ChannelLoop` - 26 edges
6. `Keys` - 18 edges
7. `ConfigError` - 15 edges
8. `load_config()` - 14 edges
9. `Outcome` - 14 edges
10. `main()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `main()` --uses--> `ConfigError`  [INFERRED]
  main.py → funnel_bot/config.py
- `test_announcement_can_be_disabled()` --uses--> `Keys`  [INFERRED]
  tests/test_quest.py → funnel_bot/context.py
- `test_background_loop_runs_and_respects_disable()` --uses--> `Keys`  [INFERRED]
  tests/test_scheduler_and_db.py → funnel_bot/context.py
- `test_tick_deletes_previous_before_posting()` --uses--> `Keys`  [INFERRED]
  tests/test_scheduler_and_db.py → funnel_bot/context.py
- `ctx()` --uses--> `BotContext`  [INFERRED]
  tests/conftest.py → funnel_bot/context.py

## Import Cycles
- None detected.

## Communities (11 total, 2 thin omitted)

### Community 0 - "admin.py"
Cohesion: 0.11
Nodes (5): register_all(), register(), check_channels(), is_member(), setup_logging()

### Community 1 - "Database"
Cohesion: 0.10
Nodes (8): Database, now(), UserRow, main(), db(), test_broadcast_targets_and_stats(), test_mark_completed_is_atomic(), test_upsert_keeps_first_source()

### Community 2 - "config.py"
Cohesion: 0.11
Nodes (21): _admin_ids(), _bool(), _channel_id(), Config, ConfigError, _int(), load_config(), _loop_media() (+13 more)

### Community 3 - "register"
Cohesion: 0.07
Nodes (20): _requirements(), run_checks(), _fmt_ts(), _media_label(), _parse_user_id(), register(), ban(), broadcast_cb() (+12 more)

### Community 4 - "texts.py"
Cohesion: 0.12
Nodes (16): RequiredChannel, on_join_request(), _edit(), register(), start(), verify(), announce_unlock(), announcement_keyboard() (+8 more)

### Community 5 - "ChannelLoop"
Cohesion: 0.15
Nodes (5): ChannelLoop, test_background_loop_runs_and_respects_disable(), test_last_message_id_survives_restart(), test_loop_survives_errors(), test_tick_deletes_previous_before_posting()

### Community 6 - "BotContext"
Cohesion: 0.12
Nodes (7): BotContext, issue_new_link(), link_for_returning_user(), _permanent_link(), revoke_link(), _unique_link(), set_commands()

### Community 7 - "verify_user"
Cohesion: 0.26
Nodes (15): Outcome, verify_user(), VerifyResult, tg_user(), join_all(), test_announcement_can_be_disabled(), test_announcement_escapes_html(), test_banned_user_is_rejected() (+7 more)

### Community 9 - "Telegram Verification Funnel Bot"
Cohesion: 0.18
Nodes (10): 1. The plan, step by step, 2. Telegram setup (do this first), 3. Configuration (`.env`), 4. Run, 5. Commands, 6. Extra features included, 7. Database schema, 8. Notes and limitations (+2 more)

## Knowledge Gaps
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BotContext` connect `BotContext` to `admin.py`, `Database`, `config.py`, `register`, `texts.py`, `ChannelLoop`, `verify_user`?**
  _High betweenness centrality (0.286) - this node is a cross-community bridge._
- **Are the 19 inferred relationships involving `BotContext` (e.g. with `_requirements()` and `run_checks()`) actually correct?**
  _`BotContext` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Should `admin.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10821256038647344 - nodes in this community are weakly interconnected._
- **Why does `Database` connect `Database` to `admin.py`, `config.py`, `BotContext`?**
  _High betweenness centrality (0.157) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Database` (e.g. with `BotContext` and `db()`) actually correct?**
  _`Database` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Should `Database` be split into smaller, more focused modules?**
  _Cohesion score 0.10104529616724739 - nodes in this community are weakly interconnected._
- **Why does `register()` connect `register` to `admin.py`, `config.py`, `BotContext`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._