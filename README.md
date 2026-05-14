# Cross Platform ChatBot

一个基于 Python 和 NoneBot2 的跨平台聊天 bot 项目骨架。项目参考 NoneBot2 的“驱动器 + 适配器 + 插件”设计，可以按需接入 QQ、OneBot、Telegram、Discord、飞书、GitHub 等平台。

## 功能

- 多平台适配器自动注册：安装了哪个适配器，就注册哪个适配器。
- 插件式功能目录：`src/plugins` 下每个目录都是一个功能模块。
- 内置基础功能：`/ping`、`/help`、`/about`、`/status`。
- 内置工具功能：`/echo`、`/calc`、`/choose`、`/roll`、`/time`。
- 预留配置层：通过 `.env` 和 `CHATBOT_` 前缀控制业务配置。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[onebot,telegram,discord,feishu,qq,github,dev]"
cp .env.example .env
python bot.py
```

如果只需要某个平台，可以只安装对应 extra，例如：

```bash
python -m pip install -e ".[onebot,dev]"
```

## 目录结构

```text
.
├── bot.py                  # NoneBot2 启动入口
├── pyproject.toml          # 项目依赖和 NoneBot2 插件配置
├── src
│   ├── chatbot             # 共享配置和工具
│   └── plugins             # 业务插件
├── tests                   # 测试
└── scripts                 # 本地辅助脚本
```

## 新增功能插件

在 `src/plugins` 下新建目录即可。例如 `src/plugins/weather/__init__.py`：

```python
from nonebot import on_command
from nonebot.params import CommandArg

weather = on_command("weather", aliases={"天气"}, priority=5, block=True)


@weather.handle()
async def handle_weather(args=CommandArg()):
    city = args.extract_plain_text().strip() or "上海"
    await weather.finish(f"{city} 天气功能待接入。")
```

## 平台接入思路

1. 安装目标平台适配器，例如 `.[onebot]` 或 `.[telegram]`。
2. 按对应适配器文档配置 `.env` 中的 token、secret、webhook 或 WebSocket 地址。
3. 启动 `python bot.py`。
4. 发送 `/ping` 或 `/help` 验证 bot 是否可用。

## 本地检查

```bash
python scripts/check_syntax.py
pytest
ruff check .
```
