from __future__ import annotations

import platform
from datetime import datetime, timezone

from nonebot import get_driver, on_command, on_message
from nonebot.adapters import Bot, Event

from src.chatbot.runtime import record_message
from src.chatbot.settings import get_settings
from src.chatbot.text import user_id


settings = get_settings()
started_at = datetime.now(timezone.utc)
status = on_command("status", aliases={"状态"}, priority=5, block=True)
message_recorder = on_message(priority=1, block=False)


def is_owner(event: Event) -> bool:
    owners = {str(owner) for owner in settings.owner_ids}
    return not owners or user_id(event) in owners


@status.handle()
async def handle_status(event: Event) -> None:
    if not is_owner(event):
        await status.finish("你没有权限查看运行状态。")

    driver = get_driver()
    adapters = ", ".join(driver._adapters.keys()) or "none"
    uptime = datetime.now(timezone.utc) - started_at
    await status.finish(
        "\n".join(
            [
                f"Bot: {settings.bot_name}",
                f"Python: {platform.python_version()}",
                f"Driver: {driver.type}",
                f"Adapters: {adapters}",
                f"Uptime: {str(uptime).split('.')[0]}",
            ]
        )
    )


@message_recorder.handle()
async def handle_message_record(bot: Bot, event: Event) -> None:
    record_message(bot, event)
