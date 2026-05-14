from __future__ import annotations

from nonebot import get_driver, on_command, on_message
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import to_me

from src.chatbot.settings import get_settings
from src.chatbot.text import plain_text


settings = get_settings()

ping = on_command("ping", aliases={"测试", "ping"}, priority=5, block=True)
help_cmd = on_command("help", aliases={"帮助", "菜单"}, priority=5, block=True)
about = on_command("about", aliases={"关于"}, priority=5, block=True)
chat = on_message(rule=to_me(), priority=50, block=False)


@ping.handle()
async def handle_ping() -> None:
    await ping.finish("pong")


@help_cmd.handle()
async def handle_help() -> None:
    await help_cmd.finish(
        "\n".join(
            [
                f"{settings.bot_name} 可用指令：",
                "/ping - 测试 bot 是否在线",
                "/echo <内容> - 复读一段文本",
                "/calc <表达式> - 安全计算四则运算",
                "/choose A | B | C - 随机选择",
                "/roll [面数] - 掷骰子，默认 100",
                "/time [时区] - 查看当前时间，例如 /time Asia/Shanghai",
                "/status - 查看运行状态",
            ]
        )
    )


@about.handle()
async def handle_about() -> None:
    await about.finish(
        f"{settings.bot_name} 是一个基于 NoneBot2 的跨平台聊天 bot，"
        "通过适配器接入 QQ、Telegram、Discord、飞书、OneBot 等平台。"
    )


@chat.handle()
async def handle_mention(matcher: Matcher, event: Event) -> None:
    text = plain_text(event)
    if not text:
        return
    lowered = text.lower()
    if lowered in {"help", "帮助", "菜单"}:
        await matcher.finish("发送 /help 查看可用功能。")
    if any(word in lowered for word in ("hello", "hi", "你好")):
        await matcher.finish(f"你好，我是 {settings.bot_name}。发送 /help 可以看菜单。")


driver = get_driver()


@driver.on_startup
async def _startup() -> None:
    driver.logger.info("%s is starting", settings.bot_name)
