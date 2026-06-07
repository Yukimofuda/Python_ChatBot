from __future__ import annotations

from nonebot import get_driver, on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from src.chatbot.bot_brain import build_demo_brain
from src.chatbot.commands import ALIASES, COMMANDS
from src.chatbot.message_render import render_command_help, truncate_text
from src.chatbot.settings import get_settings
from src.chatbot.text import plain_text, raw_actor_id


settings = get_settings()
ping = on_command("ping", aliases={"测试", "ping"}, priority=5, block=True)
help_cmd = on_command("bot", aliases={"cbhelp", "crosshelp", "机器人帮助", "bothelp"}, priority=5, block=True)
about = on_command("about", aliases={"关于"}, priority=5, block=True)
chat = on_message(rule=to_me(), priority=50, block=False)
brain = build_demo_brain()


@ping.handle()
async def handle_ping() -> None:
    await ping.finish("pong")


@help_cmd.handle()
async def handle_help(args=CommandArg()) -> None:
    topic = args.extract_plain_text().strip().lower()
    if not topic:
        await help_cmd.finish(render_command_help(COMMANDS))

    topic = ALIASES.get(topic, topic)
    if topic == "all":
        await help_cmd.finish(render_command_help(COMMANDS, title="全部命令"))
    if topic not in COMMANDS:
        await help_cmd.finish("没找到这个分类。试试 /bot all。")
    await help_cmd.finish(render_command_help({topic: COMMANDS[topic]}, title=f"/bot {topic}"))


@about.handle()
async def handle_about() -> None:
    await about.finish(
        truncate_text(
            f"{settings.bot_name}: public-safe NoneBot2 scaffold with utilities, points, sign-in, "
            "Bilibili parsing, local admin web, and a neutral bot_brain pipeline.",
            900,
        )
    )


@chat.handle()
async def handle_mention(matcher: Matcher, bot: Bot, event: Event) -> None:
    text = plain_text(event)
    if not text or text.startswith(("/", "!")):
        return
    if str(raw_actor_id(event)) == str(bot.self_id):
        return
    lowered = text.lower()
    if lowered in {"help", "帮助", "菜单", "cbhelp", "bot", "bothelp"}:
        await matcher.finish("发送 /bot 查看命令菜单。")

    reply = brain.reply_to_text(text)
    await matcher.finish(reply)


driver = get_driver()


@driver.on_startup
async def _startup() -> None:
    driver.logger.info("%s is starting", settings.bot_name)
