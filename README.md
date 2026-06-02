# Python Bot Public Base

Python Bot Public Base 是从现行 bot 工程中提炼出来的公开仓库版本。它保留通用机器人运行框架、常用插件和本地管理能力，不包含任何人格设定文本、角色设定、私有记忆、研究报告、运行日志或本地密钥。

## 版本定位

这一版适合作为公开 GitHub 仓库的基础版：

- 基于 NoneBot2 和 OneBot V11，默认面向群聊/私聊机器人运行。
- 保留 `/ping`、`/bot`、`/about`、工具命令、娱乐命令、签到、积分、B 站视频解析和本地 Admin Web。
- 保留一个最小 OpenAI-compatible LLM 调用封装，但默认关闭，且不内置任何人格或系统消息。
- 移除角色设定文本、人格引擎、私有记忆系统、治理重构文档、锁定报告、本地数据、备份文件和环境密钥。

## 目录结构

```text
.
├── bot.py                  # NoneBot2 入口
├── pyproject.toml          # 依赖与 NoneBot 插件配置
├── .env.example            # 可公开的环境变量模板
├── src/
│   ├── chatbot/            # 通用运行、配置、存储、权限、管理台、工具逻辑
│   └── plugins/            # core / utility / fun / admin / sign / points / bilibili
└── tests/                  # 公开版保留的通用单元测试
```

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
cp .env.example .env
python bot.py
```

OneBot V11 客户端连接地址：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

启动后可以访问：

```text
http://127.0.0.1:8080/admin
http://127.0.0.1:8080/health
```

## 常用配置

`.env.example` 中的配置可以复制为 `.env` 后修改：

- `CHATBOT_BOT_NAME`: Bot 显示名称，默认使用通用值 `Bot`，可以按公开仓库需要自行改名。
- `CHATBOT_OWNER_IDS`: 拥有者账号 ID 列表。
- `CHATBOT_ADMIN_IDS`: 管理员账号 ID 列表。
- `CHATBOT_ADMIN_TOKEN`: Admin Web 发送消息接口的管理 token。
- `CHATBOT_DATA_DIR`: 本地 JSON 数据目录，默认 `data`。
- `CHATBOT_LLM_ENABLED`: 是否启用可选 LLM 调用，默认 `false`。
- `CHATBOT_LLM_API_KEY`: 可选 LLM API key，不要提交到公开仓库。
- `CHATBOT_BILIBILI_DOWNLOAD_DIR`: B 站视频临时下载目录。

## 命令概览

- `/ping`: 健康检查。
- `/bot [分类]`: 查看命令菜单，支持 `/bot all`。
- `/about`: 查看当前公开版说明。
- `/echo 内容`: 复读。
- `/calc 表达式`: 安全计算。
- `/choose A | B`: 随机选择。
- `/roll [面数]`: 掷骰。
- `/time [时区]`: 查看时间。
- `/fortune`、`/draw`、`/8ball`、`/rate`、`/crazy`: 轻量娱乐命令。
- `/sign`、`/sign info`、`/sign rank`、`/sign calendar`: 签到。
- `/points`、`/points rank`、`/points give 用户ID 数量`: 积分。
- `/bili status`、`/bili on`、`/bili off`、`/bili clean`: B 站解析管理。
- `/status`: 管理员运行状态。

## 版本迭代说明

### Public Base 0.1.0

- 从现行工程抽取通用运行框架，保留 NoneBot2 启动入口和多适配器注册机制。
- 将帮助入口统一改为 `/bot`，移除人格、梦境、环境回复、私有记忆等命令分组。
- 去掉原项目固定 bot 名称，默认只使用通用显示值 `Bot`，并清除角色名称和人格化帮助文案。
- 保留签到、积分、B 站解析、Admin Web 和基础工具插件。
- 提供公开安全的 `.env.example`，只保留占位配置，不包含真实 token、账号或 API key。
- 保留通用单元测试，移除依赖人格设定和私有记忆架构的测试。

## 公开仓库边界

本目录刻意不包含以下内容：

- 人格设定文本、角色设定、私有风格指南。
- 私有记忆、社交认知、身份治理、删除治理和迁移实验代码。
- 私有工作记忆目录、研究报告、ADR 草稿、运行数据、SQLite/JSON 数据库、日志和备份文件。
- `.env`、真实 token、API key、账号 ID、平台内部标识和本地客户端路径。

提交公开仓库前建议再运行：

```bash
python -m pytest -q
rg -n "api[_-]?key|token|secret|password" .
```
