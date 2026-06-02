from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.chatbot.settings import get_settings
from src.chatbot.storage import JsonPluginStorage

if TYPE_CHECKING:
    from nonebot.adapters import Event


TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]{2,12}")
SENSITIVE_RE = re.compile(r"(token|api[_-]?key|密码|passwd|password|secret)", re.I)
MOOD_WORDS = {
    "happy": ("哈哈", "笑死", "绷不住", "好耶", "开心"),
    "angry": ("傻逼", "垃圾", "滚", "气死"),
    "confused": ("？", "?", "怎么", "为啥", "啥"),
    "joking": ("草", "乐", "绷", "怪", "离谱"),
}

store = JsonPluginStorage("group_memory", default={"groups": {}})


def scope_id(event: "Event") -> str:
    from src.chatbot.permissions import get_group_id, get_user_id

    return get_group_id(event) or f"private:{get_user_id(event)}"


def remember_event(event: "Event") -> None:
    from src.chatbot.permissions import get_user_id
    from src.chatbot.text import plain_text

    text = plain_text(event)
    if not text or SENSITIVE_RE.search(text):
        return
    group = scope_id(event)
    user = get_user_id(event)
    now = datetime.now(timezone.utc).isoformat()

    def mutate(data: dict[str, Any]) -> None:
        groups = data.setdefault("groups", {})
        memory = groups.setdefault(group, {"messages": [], "users": {}, "keywords": {}})
        messages = memory.setdefault("messages", [])
        messages.append({"time": now, "user_id": user, "text": text[:200]})
        del messages[: -get_settings().memory_max_messages_per_group]
        user_data = memory.setdefault("users", {}).setdefault(
            user,
            {"count": 0, "keywords": {}, "last_seen": now},
        )
        user_data["count"] = int(user_data.get("count", 0)) + 1
        user_data["last_seen"] = now
        for token in extract_keywords(text):
            memory["keywords"][token] = int(memory["keywords"].get(token, 0)) + 1
            user_data["keywords"][token] = int(user_data["keywords"].get(token, 0)) + 1

    store.update(mutate)


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    tokens = [token for token in TOKEN_RE.findall(text) if not token.isdigit()]
    return [token for token, _ in Counter(tokens).most_common(limit)]


def group_snapshot(group: str) -> dict[str, Any]:
    memory = store.read().get("groups", {}).get(group, {})
    messages = memory.get("messages", [])
    keywords = sorted(memory.get("keywords", {}).items(), key=lambda item: item[1], reverse=True)
    users = sorted(
        memory.get("users", {}).items(),
        key=lambda item: int(item[1].get("count", 0)),
        reverse=True,
    )
    return {
        "message_count": len(messages),
        "top_keywords": keywords[:8],
        "active_users": [(user, data.get("count", 0)) for user, data in users[:8]],
        "mood": detect_mood([item.get("text", "") for item in messages[-30:]]),
    }


def user_snapshot(group: str, user_id: str) -> dict[str, Any]:
    user = store.read().get("groups", {}).get(group, {}).get("users", {}).get(user_id, {})
    keywords = sorted(user.get("keywords", {}).items(), key=lambda item: item[1], reverse=True)
    return {"count": user.get("count", 0), "top_keywords": keywords[:5]}


def detect_mood(messages: list[str] | str) -> str:
    if isinstance(messages, str):
        messages = [messages]
    text = "\n".join(messages)
    if not text.strip():
        return "quiet"
    scores = {
        mood: sum(text.count(word) for word in words)
        for mood, words in MOOD_WORDS.items()
    }
    if len(messages) >= 18:
        scores["active"] = scores.get("active", 0) + 2
    mood, score = max(scores.items(), key=lambda item: item[1])
    return mood if score > 0 else "quiet"
