from __future__ import annotations

from nonebot import get_driver, on_command, on_message
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from src.chatbot.commands import ALIASES, COMMANDS
from src.chatbot.message_render import render_command_help, truncate_text
from src.chatbot.settings import get_settings
from src.chatbot.text import plain_text


settings = get_settings()

ping = on_command("ping", aliases={"test"}, priority=5, block=True)
help_cmd = on_command("cbhelp", aliases={"bothelp", "机器人帮助"}, priority=5, block=True)
about = on_command("about", aliases={"关于"}, priority=5, block=True)
chat = on_message(rule=to_me(), priority=50, block=False)


@ping.handle()
async def handle_ping() -> None:
    await ping.finish("pong")


@help_cmd.handle()
async def handle_help(args=CommandArg()) -> None:
    topic = args.extract_plain_text().strip().lower()
    if not topic:
        await help_cmd.finish(render_command_help(COMMANDS, title="Python Bot Commands"))

    topic = ALIASES.get(topic, topic)
    if topic == "all":
        await help_cmd.finish(render_command_help(COMMANDS, title="Python Bot Commands"))
    if topic not in COMMANDS:
        await help_cmd.finish("Unknown category. Try /cbhelp all or /cbhelp utility.")
    await help_cmd.finish(render_command_help({topic: COMMANDS[topic]}, title=f"/cbhelp {topic}"))


@about.handle()
async def handle_about() -> None:
    await about.finish(
        truncate_text(
            "Python Bot\n"
            "A NoneBot2 + OneBot V11 + NapCat QQ chatbot template.\n"
            "Use /cbhelp to view available commands.",
            900,
        )
    )


@chat.handle()
async def handle_mention(matcher: Matcher, event: Event) -> None:
    text = plain_text(event)
    if not text:
        return
    lowered = text.lower()
    if lowered in {"help", "帮助", "菜单", "cbhelp", "bothelp"}:
        await matcher.finish("Send /cbhelp to view the command menu.")


driver = get_driver()


@driver.on_startup
async def _startup() -> None:
    driver.logger.info("%s is starting", settings.bot_name)
