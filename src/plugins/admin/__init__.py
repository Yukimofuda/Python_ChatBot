from __future__ import annotations

import platform
from datetime import datetime, timezone

from nonebot import get_driver, on_command
from nonebot.adapters import Event

from src.chatbot.settings import get_settings
from src.chatbot.text import user_id


settings = get_settings()
started_at = datetime.now(timezone.utc)
status = on_command("status", aliases={"状态"}, priority=5, block=True)


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
