from __future__ import annotations

from src.chatbot.bot_brain.context import build_context
from src.chatbot.bot_brain.critic import review_reply
from src.chatbot.bot_brain.fallback import fallback_reply
from src.chatbot.bot_brain.generator import generate_reply
from src.chatbot.bot_brain.local_store import LocalFactStore
from src.chatbot.bot_brain.observation import normalize_observation
from src.chatbot.bot_brain.planner import plan_reply
from src.chatbot.bot_brain.retrieval import retrieve_memories
from src.chatbot.bot_brain.types import BrainMemory, BrainReply


class DemoBrain:
    def __init__(self, store: LocalFactStore | None = None) -> None:
        self.store = store or LocalFactStore()

    def reply_to_text(self, text: str, *, scope: str = "public-chat") -> str:
        observation = normalize_observation(text, scope=scope)
        plan = plan_reply(observation)
        memories = retrieve_memories(self.store, observation)
        context = build_context(observation, memories)
        reply = generate_reply(plan, context)
        verdict = review_reply(reply)
        if not verdict.ok:
            return fallback_reply().text
        if reply.used_fallback:
            return fallback_reply().text
        return reply.text


def build_demo_brain() -> DemoBrain:
    store = LocalFactStore()
    store.add(
        BrainMemory(
            scope="public-chat",
            topic="help",
            content="这是公开版基础机器人，支持命令菜单、签到、积分、工具、娱乐和 B 站解析。",
            tags=("help", "about"),
        )
    )
    store.add(
        BrainMemory(
            scope="public-chat",
            topic="bilibili",
            content="B 站链接会先发封面和简介，再统一走文件上传链路处理视频。",
            tags=("bilibili", "video"),
        )
    )
    return DemoBrain(store=store)
