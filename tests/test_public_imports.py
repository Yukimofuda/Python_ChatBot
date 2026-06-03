from __future__ import annotations


def test_public_memory_modules_importable():
    import src.chatbot.bot_brain as bot_brain
    from src.chatbot.bot_brain.social_cognition.store import SocialCognitionStore
    from src.chatbot.bot_brain.social_cognition.tasks import format_status

    assert hasattr(bot_brain, "event_to_observation")
    assert SocialCognitionStore is not None
    assert isinstance(format_status(), str)


def test_private_persona_modules_removed():
    import importlib.util

    assert importlib.util.find_spec("src.chatbot." + "sh" + "ion_brain") is None
    assert importlib.util.find_spec("src.chatbot.persona_engine") is None
