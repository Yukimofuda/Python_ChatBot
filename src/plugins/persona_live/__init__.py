from __future__ import annotations

from typing import Any

from nonebot import on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.params import CommandArg
from nonebot.rule import to_me

from src.chatbot.memory import group_snapshot, scope_id
from src.chatbot.message_render import truncate_text
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.persona_engine import PERSONA_NAME, render_identity, render_profile, render_rules, render_world
from src.chatbot.shion_brain import brain, event_to_observation
from src.chatbot.shion_brain.persona_engine import PersonaEngine
from src.chatbot.shion_brain.thinking import with_delayed_thinking
from src.chatbot.storage import JsonPluginStorage
from src.chatbot.text import plain_text


store = JsonPluginStorage("persona_live", default={"groups": {}})
persona_engine = PersonaEngine()
persona = on_command("persona", aliases={"小栞状态", "人设"}, priority=5, block=True)
persona_chat = on_message(rule=to_me(), priority=35, block=False)


@persona.handle()
async def handle_persona(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    group = scope_id(event)
    command, _, rest = text.partition(" ")
    if not text:
        await persona.finish(render_identity())
    if command == "today":
        await persona.finish(persona_engine.status_text(group, brain.mood_engine.get(group)))
    if command == "mood":
        await persona.finish(persona_engine.status_text(group, brain.mood_engine.get(group)))
    if command == "intro":
        observation = event_to_observation(DummyBot(), event)
        reply = await with_delayed_thinking(brain.generate_persona_intro(observation), persona.send)
        await persona.finish(truncate_text(reply, 900))
    if command == "profile":
        await persona.finish(truncate_text(render_profile(), 1200))
    if command == "world":
        await persona.finish(render_world())
    if command == "rules":
        await persona.finish(truncate_text(render_rules(), 1200))
    if command == "style":
        await persona.finish(style_text())
    if command == "memory":
        await persona.finish(memory_text(group))
    if command in {"on", "off"}:
        if not require_admin(event):
            await persona.finish("这个开关要管理员来拨。小栞不能随便乱改群设定。")
        set_group_value(group, "enabled", command == "on")
        await persona.finish(f"persona_live 已{'开启' if command == 'on' else '关闭'}。")
    if command == "set":
        if not require_admin(event):
            await persona.finish("基础人设设置需要管理员权限。")
        content = rest.strip()
        if len(content) > 300:
            await persona.finish("设定太长啦，最多 300 字。")
        set_group_value(group, "base_prompt", content)
        await persona.finish("我记住这版基础设定了。会慢慢融进说话风格里。")
    if command == "reset":
        if not require_admin(event):
            await persona.finish("重置人设需要管理员权限。")
        reset_group(group)
        await persona.finish("基础设定和情绪状态已重置。小栞回到默认观测模式。")

    await persona.finish(
        "用法：/persona today、/persona mood、/persona profile、/persona world、"
        "/persona rules、/persona style、/persona memory、/persona on/off"
    )


@persona_chat.handle()
async def handle_persona_chat(bot: Bot, event: Event) -> None:
    if str(get_user_id(event)) == str(bot.self_id):
        return
    text = plain_text(event)
    if not text:
        return
    group = scope_id(event)
    config = group_config(group)
    if not config.get("enabled", True):
        return

    observation = event_to_observation(bot, event)
    reply = await with_delayed_thinking(brain.respond_direct(observation), persona_chat.send)
    if not reply:
        return
    await persona_chat.finish(truncate_text(reply, 600))


def group_config(group: str) -> dict[str, Any]:
    return store.read().get("groups", {}).get(group, {})


def set_group_value(group: str, key: str, value: Any) -> None:
    def mutate(data: dict[str, Any]) -> None:
        config = data.setdefault("groups", {}).setdefault(group, {})
        config[key] = value

    store.update(mutate)


def reset_group(group: str) -> None:
    def mutate(data: dict[str, Any]) -> None:
        config = data.setdefault("groups", {}).setdefault(group, {})
        config["base_prompt"] = ""
        config["mood"] = {}

    store.update(mutate)


def memory_text(group: str) -> str:
    snapshot = group_snapshot(group)
    top_words = "、".join(word for word, _ in snapshot["top_keywords"][:6]) or "暂无"
    active = "、".join(user for user, _ in snapshot["active_users"][:5]) or "暂无"
    return (
        "小栞群聊观测：\n"
        f"记忆消息数：{snapshot['message_count']}\n"
        f"群聊氛围：{snapshot['mood']}\n"
        f"高频词：{top_words}\n"
        f"最近活跃：{active}\n"
        "我只记录公开聊天里的轻量统计，不记录 token、密码和私密信息。"
    )


def memory_summary(group: str) -> str:
    snapshot = group_snapshot(group)
    top_words = "、".join(word for word, _ in snapshot["top_keywords"][:6]) or "暂无"
    return f"氛围={snapshot['mood']}；消息数={snapshot['message_count']}；热词={top_words}"


def style_text() -> str:
    return (
        f"{PERSONA_NAME} 说话风格：\n"
        "短句偏多，活泼但不吵；技术问题认真，日常会轻轻吐槽；"
        "被夸会嘴硬，被求助会先稳住对方；不会每条消息都回复。"
    )


class DummyBot:
    self_id = "shion"
