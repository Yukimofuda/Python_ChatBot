# Python Bot Public Base

A public-safe Python chatbot scaffold powered by **NoneBot2** and **OneBot V11**.

This repository is a cleaned public base extracted from a private bot project. It keeps reusable runtime, common plugins, Admin Web, local JSON storage, Bilibili parsing support, and a generic bot-memory subsystem. It intentionally removes private persona text, role lore, local paths, runtime data, logs, backups, private prompts, and environment secrets.

## What is included

- NoneBot2 application entry in `bot.py`.
- OneBot V11 reverse WebSocket support by default.
- Optional adapter registration for installed adapters.
- Public commands: `/ping`, `/bot`, `/about`, utility commands, fun commands, sign-in, points, Bilibili management, and `/status`.
- Local Admin Web routes: `/admin`, `/health`, `/admin/api/status`, `/admin/api/messages`, `/admin/api/send`.
- Generic memory commands backed by `src/chatbot/bot_brain/social_cognition/`:
  - `/memory status`
  - `/memory inspect <账号ID或昵称>`
  - `/memory list <账号ID或昵称> [--all]`
  - `/memory add <账号ID或昵称> <记忆内容> [#alias|#nickname|#profile]`
  - `/memory edit <memory_id> <新内容>`
  - `/memory delete <memory_id|账号ID 关键词>`
  - `/memory restore <memory_id>`
  - `/memory audit [memory_id|账号ID]`
- Generic `bot_brain` memory/governance code. The old private `bot_brain` package name has been removed.

## Public memory boundary

`src/chatbot/bot_brain/` keeps the memory, identity-resolution, alias-index, CRUD, governance, migration, retrieval, and output-guard pieces that are useful for a generic bot. Persona/lore/roleplay modules were removed.

This public base does **not** include:

- Private persona prompts or role settings.
- Character/lore files.
- Private owner binding or hard-coded personal identifiers.
- Local runtime databases, logs, reports, or backups.
- Generated caches or virtual environments.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
cp .env.example .env
python bot.py
```

OneBot V11 reverse WebSocket endpoint:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

Local web endpoints:

```text
http://127.0.0.1:8080/admin
http://127.0.0.1:8080/health
```

## Development checks

```bash
python scripts/check_syntax.py
python -m pytest -q
python -m ruff check .
```

Before public release, scan for accidental secrets or private artifacts:

```bash
rg -n "api[_-]?key|token|secret|password|passwd|cookie|session|/Users|private_name_or_id" .
find . -maxdepth 4 \( -name "*.pyc" -o -name "__pycache__" -o -name ".env" -o -name "*.sqlite" -o -name "*.db" -o -name "*.log" \) -print
```

## Repository safety policy

Do not commit `.env`, local account IDs, API keys, cookies, database files, logs, downloaded media, backups, private prompts, or private character/lore material. If any secret was exposed before publication, rotate it before continuing development.
