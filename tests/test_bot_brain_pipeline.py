from src.chatbot.bot_brain import build_demo_brain


def test_demo_brain_answers_help_query():
    brain = build_demo_brain()

    reply = brain.reply_to_text("这个公开版支持什么功能？")

    assert "公开版" in reply or "支持" in reply


def test_demo_brain_uses_fallback_for_empty_text():
    brain = build_demo_brain()

    reply = brain.reply_to_text("")

    assert "/bot" in reply
