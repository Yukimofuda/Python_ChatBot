from __future__ import annotations

from src.chatbot.bot_brain.types import BrainReply, ContextBundle, ReplyPlan


def generate_reply(plan: ReplyPlan, context: ContextBundle) -> BrainReply:
    if plan.requires_fallback:
        return BrainReply("", used_fallback=True, notes=("empty_input",))

    if context.memories:
        summary = "；".join(item.content for item in context.memories[:2])
        if plan.intent == "answer":
            text = f"我先按公开版的通用上下文回答：{summary}"
        else:
            text = f"收到，这里有一条相关线索：{summary}"
        return BrainReply(text=text[: plan.max_length], notes=context.notes)

    if plan.intent == "answer":
        text = "我可以帮你处理通用问题；更具体一点，我会更容易回答。"
    else:
        text = "我收到啦。需要的话可以继续说具体一点。"
    return BrainReply(text=text[: plan.max_length], notes=context.notes)
