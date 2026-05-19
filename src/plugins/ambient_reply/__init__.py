from __future__ import annotations

from typing import Any

from nonebot import on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.params import CommandArg

from src.chatbot.cooldown import CooldownManager
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.shion_brain import brain, event_to_observation
from src.chatbot.storage import JsonPluginStorage
from src.chatbot.memory import scope_id
from src.chatbot.text import plain_text
from src.chatbot.shion_brain.thinking import with_delayed_thinking


store = JsonPluginStorage("ambient_reply", default={"groups": {}})
cooldown = CooldownManager()
ambient = on_command("ambient", aliases={"氛围"}, priority=5, block=True)
observer = on_message(priority=45, block=False)

LEVELS = {"低": ("low", 1800), "中": ("medium", 600), "高": ("high", 180)}
LEVEL_SECONDS = {"low": 1800, "medium": 600, "high": 180}


@ambient.handle()
async def handle_ambient(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    group = scope_id(event)
    command, _, rest = text.partition(" ")
    if command == "status" or not text:
        config = group_config(group)
        await ambient.finish(
            f"ambient_reply：{'开启' if config.get('enabled', True) else '关闭'}\n"
            f"频率：{config.get('level', 'low')}\n"
            "小栞会很克制地接话，不会每条都回。"
        )
    if command in {"on", "off"}:
        if not require_admin(event):
            await ambient.finish("氛围插话开关需要管理员权限。")
        set_config(group, enabled=command == "on")
        await ambient.finish(f"ambient_reply 已{'开启' if command == 'on' else '关闭'}。")
    if command == "level":
        if not require_admin(event):
            await ambient.finish("调插话频率需要管理员权限。")
        level = LEVELS.get(rest.strip())
        if not level:
            await ambient.finish("用法：/ambient level 低/中/高")
        set_config(group, level=level[0])
        await ambient.finish(f"插话频率已设为：{rest.strip()}。我会注意分寸。")
    if command == "test":
        await ambient.finish("测试模式：我会把下一条普通群消息送进 Shion Brain 观察，不再用关键词固定回复。")
    await ambient.finish("用法：/ambient status、/ambient on/off、/ambient level 低/中/高")


@observer.handle()
async def observe_ambient(bot: Bot, event: Event) -> None:
    if str(get_user_id(event)) == str(bot.self_id):
        return
    text = plain_text(event)
    if not text or text.startswith(("/", "!")):
        return
    group = scope_id(event)
    config = group_config(group)
    if not config.get("enabled", True):
        return
    observation = event_to_observation(bot, event)
    if observation.message_type != "group":
        return
    if observation.features.get("mentioned_by_at"):
        return
    if observation.mentions_bot:
        reply = await with_delayed_thinking(brain.observe(observation), observer.send)
    else:
        reply = await brain.observe(observation)
    if not reply:
        return
    if not observation.mentions_bot:
        level = config.get("level", "low")
        seconds = LEVEL_SECONDS.get(level, 1800)
        if cooldown.check("ambient", group_id=group, seconds=seconds, scope="group") > 0:
            return
    await observer.finish(reply)


def group_config(group: str) -> dict[str, Any]:
    return store.read().get("groups", {}).get(group, {"enabled": True, "level": "low"})


def set_config(group: str, **values: Any) -> None:
    def mutate(data: dict[str, Any]) -> None:
        config = data.setdefault("groups", {}).setdefault(group, {"enabled": True, "level": "low"})
        config.update(values)

    store.update(mutate)
