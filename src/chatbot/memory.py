from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.chatbot.permissions import event_actor_key, event_room_key
from src.chatbot.settings import get_settings
from src.chatbot.storage import JsonPluginStorage

if TYPE_CHECKING:
    from nonebot.adapters import Event


WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]{2,12}")
SENSITIVE_RE = re.compile(r"(token|api[_-]?key|密码|passwd|password|secret)", re.I)
MOOD_WORDS = {
    "happy": ("哈哈", "笑死", "好耶", "开心"),
    "confused": ("？", "?", "怎么", "为啥", "啥"),
    "joking": ("草", "乐", "绷", "怪"),
}

store = JsonPluginStorage("context_memory", default={"scopes": {}})


def scope_id(event: "Event") -> str:
    return event_room_key(event) or f"private:{event_actor_key(event)}"


def remember_event(event: "Event") -> None:
    from src.chatbot.text import plain_text

    text = plain_text(event)
    if not text or SENSITIVE_RE.search(text):
        return
    scope = scope_id(event)
    actor = event_actor_key(event)
    now = datetime.now(timezone.utc).isoformat()

    def mutate(data: dict[str, Any]) -> None:
        scopes = data.setdefault("scopes", {})
        memory = scopes.setdefault(scope, {"messages": [], "actors": {}, "keywords": {}})
        messages = memory.setdefault("messages", [])
        messages.append({"time": now, "speaker": actor, "text": text[:200]})
        del messages[: -get_settings().memory_max_messages_per_scope]
        actor_stats = memory.setdefault("actors", {}).setdefault(
            actor,
            {"count": 0, "keywords": {}, "last_seen": now},
        )
        actor_stats["count"] = int(actor_stats.get("count", 0)) + 1
        actor_stats["last_seen"] = now
        for token in extract_keywords(text):
            memory["keywords"][token] = int(memory["keywords"].get(token, 0)) + 1
            actor_stats["keywords"][token] = int(actor_stats["keywords"].get(token, 0)) + 1

    store.update(mutate)


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    tokens = [token for token in WORD_RE.findall(text) if not token.isdigit()]
    return [token for token, _ in Counter(tokens).most_common(limit)]


def scope_snapshot(scope: str) -> dict[str, Any]:
    memory = store.read().get("scopes", {}).get(scope, {})
    messages = memory.get("messages", [])
    keywords = sorted(memory.get("keywords", {}).items(), key=lambda item: item[1], reverse=True)
    actors = sorted(
        memory.get("actors", {}).items(),
        key=lambda item: int(item[1].get("count", 0)),
        reverse=True,
    )
    return {
        "message_count": len(messages),
        "top_keywords": keywords[:8],
        "active_speakers": [(actor, data.get("count", 0)) for actor, data in actors[:8]],
        "mood": detect_mood([item.get("text", "") for item in messages[-30:]]),
    }


def detect_mood(messages: list[str] | str) -> str:
    if isinstance(messages, str):
        messages = [messages]
    text = "\n".join(messages)
    if not text.strip():
        return "quiet"
    scores = {mood: sum(text.count(word) for word in words) for mood, words in MOOD_WORDS.items()}
    mood, score = max(scores.items(), key=lambda item: item[1])
    return mood if score > 0 else "quiet"
