from __future__ import annotations

from src.chatbot.bot_brain.types import BrainReply


def fallback_reply() -> BrainReply:
    return BrainReply("我先保持简洁：发送 /bot 可以查看这版公开仓库支持的功能。", used_fallback=True)
