# Python Bot

A clean NoneBot2 + OneBot V11 + NapCat QQ chatbot template with optional cognitive-memory modules.

## Stack

- Python
- NoneBot2
- OneBot V11
- NapCat QQ
- FastAPI
- WebSocket
- SQLite
- Optional Gemini-compatible LLM calls

## Message Flow

```text
QQ Client / NapCat
-> OneBot V11 reverse WebSocket
-> NoneBot2 FastAPI server
-> plugins
-> optional cognitive brain modules
```

## Install

```bash
cd Python_Bot
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` with your local ports, owner IDs, and optional API keys. Do not commit `.env`.

## Run

```bash
python bot.py
```

Configure NapCat OneBot V11 reverse WebSocket to connect to:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

## Plugins

The template includes practical plugin examples:

- `core`: `/ping`, help, status, about
- `utility`: calculation and utility commands
- `fun`: lightweight fun commands
- `admin`: local admin web/status helpers
- `bilibili`: optional Bilibili parsing/downloading
- `points` and `sign`: simple persistence examples
- `shion_lifecycle`: optional scheduled cognitive maintenance for the brain module

## Optional Cognitive Brain

`src/chatbot/shion_brain/` is a generic technical module for experimenting with:

- SQLite short-term memory
- semantic graph memory
- belief-state records
- procedural interaction memory
- reflection/distillation loops
- thought queue and agenda tree
- conservative lifecycle scheduling

Prompt files are intentionally empty in this public template. Add your own persona/style prompts locally and keep private prompts out of Git.

## Common Commands

- `/ping`
- `/cbhelp` or your configured help command
- `/about`
- `/calc 1 + 2 * 3`
- `/choose a b c`
- `/roll 1d100`
- `/time`
- `/fortune`
- `/status`

Available commands depend on which plugins you keep enabled.

## Bilibili Dependencies

The Bilibili plugin may require:

- `yt-dlp`
- `ffmpeg`

Keep downloaded media in ignored folders such as `downloads/`.

## LLM Configuration

LLM use is optional and disabled by default. For Gemini-compatible use, set local environment values in `.env`:

```env
CHATBOT_LLM_ENABLED=false
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

If generation fails, user-facing code should return a short generic failure message and log details only on the backend.

## Security

Never commit:

- `.env`
- API keys or access tokens
- `data/`
- SQLite databases
- NapCat local config
- chat logs
- downloaded media
- private prompts/persona files

If a key was ever exposed, rotate it before publishing.

## Develop Plugins

Add a plugin under `src/plugins/<plugin_name>/__init__.py`. NoneBot loads plugin directories from `pyproject.toml`:

```toml
[tool.nonebot]
plugin_dirs = ["src/plugins"]
```

Keep reusable logic in `src/chatbot/` and framework bindings in `src/plugins/`.

## Test

```bash
python scripts/check_syntax.py
python -m compileall src
pytest
```

If your venv was moved or renamed, prefer:

```bash
python -m pytest
```

instead of a stale `pytest` launcher.
