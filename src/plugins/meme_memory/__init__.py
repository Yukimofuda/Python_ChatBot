from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from nonebot import on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.params import CommandArg

from src.chatbot.cooldown import CooldownManager
from src.chatbot.memory import extract_keywords, remember_event, scope_id
from src.chatbot.message_render import paginate_list, truncate_text
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.security import validate_text_length
from src.chatbot.shion_brain import brain
from src.chatbot.shion_brain.memory_store import new_memory
from src.chatbot.storage import JsonPluginStorage
from src.chatbot.text import plain_text


store = JsonPluginStorage("meme_memory", default={"groups": {}})
cooldown = CooldownManager()
meme = on_command("meme", aliases={"群梗"}, priority=5, block=True)
observer = on_message(priority=30, block=False)


@meme.handle()
async def handle_meme(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    group = scope_id(event)
    command, _, rest = text.partition(" ")
    if not text or command == "list":
        await meme.finish(list_memes(group))
    if command == "add":
        keyword, _, explanation = rest.strip().partition(" ")
        if not keyword or not explanation:
            await meme.finish("用法：/meme add 梗名 解释")
        keyword = validate_text_length(keyword, 20)
        explanation = validate_text_length(explanation, 120)
        item = add_meme(group, keyword, explanation, get_user_id(event))
        await brain.store.initialize()
        await brain.store.add_memory(
            new_memory(
                group,
                "semantic",
                f"群梗「{keyword}」：{explanation}",
                ["meme", keyword],
                importance=0.8,
            )
        )
        await meme.finish(f"已收录群梗 #{item['id']}：{keyword}。这个梗我装进玻璃瓶了。")
    if command == "search":
        await meme.finish(search_memes(group, rest.strip()))
    if command == "random":
        await meme.finish(random_meme(group))
    if command == "stats":
        await meme.finish(meme_stats(group))
    if command in {"on", "off"}:
        if not require_admin(event):
            await meme.finish("群梗自动接话开关需要管理员权限。")
        set_enabled(group, command == "on")
        await meme.finish(f"meme_memory 已{'开启' if command == 'on' else '关闭'}。")
    if command == "del":
        await meme.finish(delete_meme(group, rest.strip(), get_user_id(event), require_admin(event)))
    await meme.finish("用法：/meme add 梗名 解释、/meme list、/meme random、/meme stats")


@observer.handle()
async def observe_meme(bot: Bot, event: Event) -> None:
    if str(get_user_id(event)) == str(bot.self_id):
        return
    text = plain_text(event)
    if not text or text.startswith(("/", "!")):
        return
    remember_event(event)
    group = scope_id(event)
    config = group_data(group)
    if not config.get("enabled", True):
        return
    items = config.get("items", [])
    for item in items:
        if item["keyword"] in text:
            hit_meme(group, int(item["id"]))
            if cooldown.check("meme_hit", group_id=group, seconds=600, scope="group") == 0:
                await brain.store.initialize()
                await brain.store.add_memory(
                    new_memory(
                        group,
                        "episodic",
                        f"刚刚有人提到了群梗「{item['keyword']}」：{item['explanation']}",
                        ["meme_hit", item["keyword"]],
                        importance=0.6,
                    )
                )
            return
    maybe_hint = suspected_meme_hint(text)
    if maybe_hint and cooldown.check("meme_hint", group_id=group, seconds=1800, scope="group") == 0:
        await observer.finish(f"我感觉「{maybe_hint}」快变成群梗了，要不要 /meme add 收录一下？")


def group_data(group: str) -> dict[str, Any]:
    return store.read().get("groups", {}).get(group, {"enabled": True, "items": [], "next_id": 1})


def add_meme(group: str, keyword: str, explanation: str, creator_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    created: dict[str, Any] = {}

    def mutate(data: dict[str, Any]) -> None:
        config = data.setdefault("groups", {}).setdefault(group, {"enabled": True, "items": [], "next_id": 1})
        item = {
            "id": int(config.get("next_id", 1)),
            "keyword": keyword,
            "explanation": explanation,
            "creator_id": creator_id,
            "created_at": now,
            "hit_count": 0,
            "last_hit_at": "",
        }
        config["next_id"] = item["id"] + 1
        config.setdefault("items", []).append(item)
        created.update(item)

    store.update(mutate)
    return created


def set_enabled(group: str, enabled: bool) -> None:
    store.update(lambda data: data.setdefault("groups", {}).setdefault(group, {}) .update({"enabled": enabled}))


def list_memes(group: str) -> str:
    items = group_data(group).get("items", [])
    if not items:
        return "这个群的梗瓶还空着。用 /meme add 梗名 解释 收录一个。"
    page_items, total = paginate_list(items, 1, 8)
    lines = [f"群梗库（第 1/{total} 页）"]
    lines.extend(f"#{item['id']} {item['keyword']}：{item['explanation']}" for item in page_items)
    return truncate_text("\n".join(lines))


def search_memes(group: str, keyword: str) -> str:
    if not keyword:
        return "用法：/meme search 关键词"
    matches = [item for item in group_data(group).get("items", []) if keyword in item["keyword"] or keyword in item["explanation"]]
    if not matches:
        return "没搜到。这个梗可能还没被小栞装瓶。"
    return truncate_text("\n".join(f"#{item['id']} {item['keyword']}：{item['explanation']}" for item in matches[:8]))


def random_meme(group: str) -> str:
    items = group_data(group).get("items", [])
    if not items:
        return "梗库是空的。小栞暂时只能假装自己很懂。"
    item = random.choice(items)
    return f"随机群梗「{item['keyword']}」：{item['explanation']}"


def meme_stats(group: str) -> str:
    items = sorted(group_data(group).get("items", []), key=lambda item: item.get("hit_count", 0), reverse=True)
    if not items:
        return "暂无群梗统计。"
    return truncate_text("\n".join(f"{item['keyword']}：命中 {item.get('hit_count', 0)} 次" for item in items[:8]))


def delete_meme(group: str, raw_id: str, user_id: str, admin: bool) -> str:
    try:
        meme_id = int(raw_id)
    except ValueError:
        return "用法：/meme del 编号"
    deleted = False

    def mutate(data: dict[str, Any]) -> None:
        nonlocal deleted
        config = data.setdefault("groups", {}).setdefault(group, {"items": []})
        kept = []
        for item in config.get("items", []):
            if item["id"] == meme_id and (admin or item.get("creator_id") == user_id):
                deleted = True
            else:
                kept.append(item)
        config["items"] = kept

    store.update(mutate)
    return "已删除这个群梗。" if deleted else "没找到，或者你没有权限删除它。"


def hit_meme(group: str, meme_id: int) -> None:
    def mutate(data: dict[str, Any]) -> None:
        for item in data.setdefault("groups", {}).setdefault(group, {}).get("items", []):
            if item["id"] == meme_id:
                item["hit_count"] = int(item.get("hit_count", 0)) + 1
                item["last_hit_at"] = datetime.now(timezone.utc).isoformat()

    store.update(mutate)


def suspected_meme_hint(text: str) -> str | None:
    words = extract_keywords(text, 3)
    return words[0] if words and len(words[0]) >= 3 and text.count(words[0]) >= 2 else None
