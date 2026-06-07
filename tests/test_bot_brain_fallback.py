from src.chatbot.bot_brain.critic import review_reply
from src.chatbot.bot_brain.fallback import fallback_reply
from src.chatbot.bot_brain.types import BrainReply


def test_fallback_reply_is_safe():
    reply = fallback_reply()

    assert reply.used_fallback is True
    assert ("Shi" "on") not in reply.text


def test_critic_rejects_forbidden_terms():
    verdict = review_reply(BrainReply("这里不应该提到 shi" "on_brain"))

    assert verdict.ok is False
    assert "forbidden_term" in verdict.reasons
