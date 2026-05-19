from __future__ import annotations

import random
from datetime import date, datetime, timezone
from typing import Any

from nonebot import on_command
from nonebot.adapters import Event
from nonebot.params import CommandArg

from src.chatbot.memory import group_snapshot, scope_id
from src.chatbot.permissions import require_admin
from src.chatbot.security import validate_text_length
from src.chatbot.shion_brain import brain
from src.chatbot.shion_brain.models import Decision, Observation, utc_now
from src.chatbot.shion_brain.reflection import ReflectionEngine
from src.chatbot.shion_brain.thinking import with_delayed_thinking
from src.chatbot.storage import JsonPluginStorage


store = JsonPluginStorage("dream_diary", default={"groups": {}})
dream = on_command("dream", aliases={"梦"}, priority=5, block=True)


@dream.handle()
async def handle_dream(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    group = scope_id(event)
    command, _, rest = text.partition(" ")
    if not text or command == "today":
        result = await with_delayed_thinking(today_dream(group), dream.send)
        await dream.finish(result)
    if command == "write":
        content = validate_text_length(rest, 120)
        add_material(group, content)
        await dream.finish("梦境素材已塞进 404 号公寓的枕头底下。")
    if command == "random":
        await dream.finish(random_dream(group))
    if command == "history":
        await dream.finish(history(group))
    if command in {"on", "off"}:
        if not require_admin(event):
            await dream.finish("梦境日记开关需要管理员权限。")
        set_enabled(group, command == "on")
        await dream.finish(f"dream_diary 已{'开启' if command == 'on' else '关闭'}。")
    await dream.finish("用法：/dream today、/dream write 内容、/dream random、/dream history")


async def today_dream(group: str) -> str:
    today = date.today().isoformat()
    config = group_data(group)
    dreams = config.get("dreams", {})
    if today not in dreams:
        await create_dream(group, today)
        dreams = group_data(group).get("dreams", {})
    return dreams[today]["text"]


async def create_dream(group: str, day: str) -> None:
    snapshot = group_snapshot(group)
    await brain.store.initialize()
    reflection = await ReflectionEngine(brain.store).reflect_group(group)
    words = [word for word, _ in snapshot["top_keywords"][:3]] or ["消息", "布丁", "deadline"]
    materials = group_data(group).get("materials", [])
    extra = random.choice(materials)["text"] if materials else random.choice(["电子奶茶", "像素雨", "B站传送门"])
    observation = Observation(
        id=f"dream-{group}-{day}",
        group_id=group,
        user_id="system",
        message_id=f"dream-{day}",
        text=(
            "请写一段小栞的群梦日记，像真实群友在凌晨随手发的短梦。"
            f"群热词：{'、'.join(words)}。梦境素材：{extra}。近期反思：{reflection}"
        ),
        timestamp=utc_now(),
        message_type="group",
        is_command=False,
        mentions_bot=False,
        features={"dream_diary": True},
    )
    decision = Decision(True, "dream", "daily dream diary", 420, 0.82, [], "normal")
    text = await brain.generator.generate(observation, brain.mood_engine.get(group), [], decision, entry="dream_diary")

    def mutate(data: dict[str, Any]) -> None:
        config = data.setdefault("groups", {}).setdefault(group, {"enabled": True, "dreams": {}, "materials": []})
        config.setdefault("dreams", {})[day] = {
            "date": day,
            "text": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    store.update(mutate)


def add_material(group: str, content: str) -> None:
    def mutate(data: dict[str, Any]) -> None:
        config = data.setdefault("groups", {}).setdefault(group, {"enabled": True, "dreams": {}, "materials": []})
        materials = config.setdefault("materials", [])
        materials.append({"text": content, "created_at": datetime.now(timezone.utc).isoformat()})
        del materials[:-20]

    store.update(mutate)


def random_dream(group: str) -> str:
    dreams = list(group_data(group).get("dreams", {}).values())
    if not dreams:
        return "梦境日记还是空的。先用 /dream today 生成今天的梦。"
    return random.choice(dreams)["text"]


def history(group: str) -> str:
    dreams = sorted(group_data(group).get("dreams", {}).values(), key=lambda item: item["date"], reverse=True)
    if not dreams:
        return "梦境日记还是空的。用 /dream today 让小栞做一个梦。"
    return "\n".join(f"{item['date']}：{item['text'].splitlines()[0]}" for item in dreams[:7])


def group_data(group: str) -> dict[str, Any]:
    return store.read().get("groups", {}).get(group, {"enabled": True, "dreams": {}, "materials": []})


def set_enabled(group: str, enabled: bool) -> None:
    store.update(lambda data: data.setdefault("groups", {}).setdefault(group, {}).update({"enabled": enabled}))
