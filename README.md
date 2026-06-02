# Python Bot Public Base

A public-safe Python chatbot scaffold powered by **NoneBot2** and **OneBot V11**.

This repository keeps the reusable bot runtime, plugin framework, local admin console, utility commands, sign-in/points examples, Bilibili parsing support, optional OpenAI-compatible LLM calling, and a lightweight public group-memory/statistics scaffold. It intentionally excludes private persona prompts, role settings, private social-cognition memory, research reports, logs, local databases, backups, and secrets.

## What this repository is for

Use this repository as a clean public base for building a group/private chat bot:

- Start a NoneBot2 application with OneBot V11 reverse WebSocket support.
- Register optional adapters only when their packages are installed and enabled.
- Keep reusable infrastructure in `src/chatbot/` and framework bindings in `src/plugins/`.
- Provide common commands such as `/ping`, `/bot`, `/about`, utility commands, fun commands, sign-in, points, Bilibili management, and admin status.
- Provide a local Admin Web console for runtime inspection and manual message sending.
- Keep LLM support optional and disabled by default.
- Keep only a lightweight public memory/statistics layer, not a private persona or social-cognition memory system.

## Current public feature set

| Area | Included |
| --- | --- |
| Runtime | NoneBot2 app entry, adapter registration, isolated Python path handling |
| Default adapter | OneBot V11 reverse WebSocket |
| Optional adapters | Telegram, Discord, Feishu, QQ, GitHub adapters through optional extras |
| Commands | Core, utility, fun, sign-in, points, Bilibili, admin status |
| Admin Web | `/admin`, `/health`, runtime status, recent messages, manual OneBot message sending |
| Storage | Local JSON storage under `CHATBOT_DATA_DIR` |
| Public memory/statistics | Recent message snippets, keyword counts, activity counts, simple mood heuristic |
| LLM | Minimal OpenAI-compatible wrapper, disabled unless configured locally |
| Tests | Public unit tests for reusable logic |

## Public memory boundary

The latest public-base iteration keeps `src/chatbot/memory.py` as a **generic local group-memory/statistics helper**. It can record recent plain-text snippets per group/private scope, count keywords, count active users, and infer a simple chat mood from recent messages.

This is deliberately not the private cognitive memory system from the original bot project:

- It does **not** include persona memory, role memory, private social-cognition profiles, identity governance, owner recognition, memory migration tools, or private reports.
- It does **not** build user-profile knowledge graphs or long-term relationship memory.
- It skips messages matching obvious secret patterns such as `token`, `api_key`, `password`, `secret`, and similar terms.
- Its retention size is controlled by `CHATBOT_MEMORY_MAX_MESSAGES_PER_GROUP`.
- Runtime data should stay local under `data/` or another configured private data directory and should not be committed.

If you want to build a stronger memory subsystem on top of this base, treat this module as a small storage/statistics example rather than as a full agent-memory architecture.

## Repository layout

```text
.
├── bot.py                  # NoneBot2 entry point and optional adapter registration
├── pyproject.toml          # Dependencies, optional extras, NoneBot plugin config, test config
├── scripts/                # Maintenance/helper scripts when present
├── src/
│   ├── chatbot/            # Runtime, settings, storage, permissions, admin web, utilities
│   └── plugins/            # NoneBot plugins: core, utility, fun, admin, sign, points, bilibili
└── tests/                  # Public unit tests for reusable, non-private logic
```

## Requirements

- Python 3.10+
- A OneBot V11-compatible client if you want to connect to QQ or another OneBot platform
- `ffmpeg` installed on the system if you want reliable Bilibili media merging/downloading

Python dependencies are declared in `pyproject.toml`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Create a local `.env` file. Do not commit it.

```bash
cat > .env <<'EOF'
CHATBOT_BOT_NAME=Bot
CHATBOT_OWNER_IDS=[]
CHATBOT_ADMIN_IDS=[]
CHATBOT_ADMIN_TOKEN=
CHATBOT_DATA_DIR=data
CHATBOT_ENABLED_ADAPTERS=["onebot_v11"]
CHATBOT_LLM_ENABLED=false
CHATBOT_LLM_API_KEY=
CHATBOT_BILIBILI_DOWNLOAD_DIR=downloads/bilibili
EOF
```

Run the bot:

```bash
python bot.py
```

Configure your OneBot V11 client to connect to the reverse WebSocket endpoint:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

After startup, the local service exposes:

```text
http://127.0.0.1:8080/admin
http://127.0.0.1:8080/health
```

## Optional adapters

The default install targets OneBot V11. Optional adapters can be installed with extras:

```bash
python -m pip install -e ".[telegram]"
python -m pip install -e ".[discord]"
python -m pip install -e ".[feishu]"
python -m pip install -e ".[qq]"
python -m pip install -e ".[github]"
```

Enable only the adapters you need in `.env`:

```env
CHATBOT_ENABLED_ADAPTERS=["onebot_v11"]
```

## Configuration

The application reads settings from `.env` with the `CHATBOT_` prefix.

| Variable | Default | Description |
| --- | --- | --- |
| `CHATBOT_BOT_NAME` | `Bot` | Display name used by status/about text |
| `CHATBOT_OWNER_IDS` | `[]` | Owner account IDs |
| `CHATBOT_ADMIN_IDS` | `[]` | Admin account IDs |
| `CHATBOT_COMMAND_START` | `["/", "!"]` | Command prefixes |
| `CHATBOT_ENABLED_ADAPTERS` | `["onebot_v11"]` | Adapter keys to register |
| `CHATBOT_ADMIN_ENABLED` | `true` | Enable local Admin Web routes |
| `CHATBOT_ADMIN_TOKEN` | empty | Token required by admin message-sending API |
| `CHATBOT_RECENT_MESSAGE_LIMIT` | `100` | Recent message buffer size |
| `CHATBOT_DATA_DIR` | `data` | Local JSON data directory |
| `CHATBOT_MEMORY_MAX_MESSAGES_PER_GROUP` | `200` | Retention limit for public group-memory snippets |
| `CHATBOT_LLM_ENABLED` | `false` | Enable optional LLM provider calls |
| `CHATBOT_LLM_BASE_URL` | Gemini-compatible default | OpenAI-compatible provider base URL |
| `CHATBOT_LLM_API_KEY` | empty | Local LLM API key; never commit it |
| `CHATBOT_LLM_MODEL` | `gemini-2.5-flash` | Model name for optional LLM calls |
| `CHATBOT_BILIBILI_ENABLED` | `true` | Enable Bilibili parsing plugin |
| `CHATBOT_BILIBILI_MAX_VIDEO_MB` | `80` | Maximum Bilibili video size |
| `CHATBOT_BILIBILI_COOLDOWN_SECONDS` | `60` | Bilibili parsing cooldown |
| `CHATBOT_BILIBILI_DOWNLOAD_DIR` | `downloads/bilibili` | Temporary Bilibili download directory |

## Command overview

| Category | Commands |
| --- | --- |
| Core | `/ping`, `/bot [分类]`, `/bot all`, `/about` |
| Utility | `/echo 内容`, `/calc 表达式`, `/choose A | B`, `/roll [面数]`, `/time [时区]` |
| Fun | `/fortune`, `/draw [主题]`, `/8ball 问题`, `/rate 对象`, `/crazy [名字]` |
| Sign-in | `/sign`, `/sign info`, `/sign rank`, `/sign calendar` |
| Points | `/points`, `/points rank`, `/points give 用户ID 数量`, `/points add 用户ID 数量`, `/points remove 用户ID 数量` |
| Bilibili | Send a Bilibili URL, `/bili status`, `/bili on`, `/bili off`, `/bili clean` |
| Admin | `/status` |

`/bot` is the canonical help entry. Legacy aliases such as `/cbhelp` and `/bothelp` may still be accepted for compatibility, but new deployments should document `/bot`.

## Admin Web

The Admin Web console is local by default and intended for development or trusted private deployment.

- `GET /health`: service health check.
- `GET /admin`: browser-based admin console.
- `GET /admin/api/status`: runtime status.
- `GET /admin/api/messages`: recent messages.
- `POST /admin/api/send`: send a OneBot message when the admin token is valid.

Set `CHATBOT_ADMIN_TOKEN` before exposing the service outside a local machine or trusted LAN.

## LLM usage

LLM calls are optional and disabled by default.

This public base does not ship any persona prompts, system prompts, private style guides, or role definitions. If you enable LLM support, add your own local prompt/configuration and keep private prompt files out of Git.

Example local configuration:

```env
CHATBOT_LLM_ENABLED=true
CHATBOT_LLM_BASE_URL=https://your-provider.example/v1
CHATBOT_LLM_API_KEY=replace-me-locally
CHATBOT_LLM_MODEL=your-model-name
```

## Development

Add reusable logic under `src/chatbot/` and keep NoneBot-specific command/event bindings under `src/plugins/`.

A new plugin can be added as:

```text
src/plugins/<plugin_name>/__init__.py
```

NoneBot loads plugin directories from `pyproject.toml`:

```toml
[tool.nonebot]
plugin_dirs = ["src/plugins"]
plugins = ["nonebot_plugin_apscheduler"]
```

## Tests and local checks

```bash
python -m pytest -q
python -m ruff check .
```

Before publishing or tagging a release, run a local secret/data scan as well:

```bash
rg -n "api[_-]?key|token|secret|password|passwd|cookie|session" .
find . -maxdepth 3 \( -name "*.db" -o -name "*.sqlite" -o -name "*.log" -o -name ".env" \) -print
```

## Security and data policy

Do not commit:

- `.env` or any real API key/token/password/cookie.
- `data/`, downloaded media, runtime JSON, SQLite files, logs, caches, or backups.
- Local OneBot/NapCat/client configuration containing account identifiers or credentials.
- Private persona prompts, role settings, social-cognition memory, identity-governance data, or research reports.
- Generated `__pycache__/` files or local virtual environments.

If a secret was ever committed or exposed, rotate it before continuing public development.

## Version notes

### Public Base 0.1.0

- Extracted the reusable NoneBot2 runtime and plugin scaffold from a larger bot project.
- Changed the public help entry to `/bot` while keeping compatibility aliases.
- Generalized QQ-specific wording to OneBot/platform wording where possible.
- Removed private persona, role, Shion-specific brain settings, private memory/governance code, reports, logs, local data, and secrets.
- Kept a lightweight public group-memory/statistics helper for local message snippets, keyword/activity counters, and simple mood inference.
- Kept sign-in, points, Bilibili parsing, utility/fun commands, Admin Web, and public unit tests.

## Public repository boundary

This repository is a base framework, not a complete private AI-agent product. The public code is designed to be safe to read, fork, and adapt. Any deployment-specific identity rules, persona design, sensitive memory, long-term cognition, private datasets, platform credentials, or local operation logs should live outside this repository.
