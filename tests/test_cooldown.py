from __future__ import annotations

from src.chatbot.cooldown import CooldownManager


def test_cooldown_returns_remaining_time():
    manager = CooldownManager()

    assert manager.check("fortune", user_id="1", seconds=10, scope="user") == 0
    assert manager.check("fortune", user_id="1", seconds=10, scope="user") > 0
    assert manager.check("fortune", user_id="2", seconds=10, scope="user") == 0


def test_cooldown_group_scope_is_shared():
    manager = CooldownManager()

    assert manager.check("ambient", group_id="100", seconds=10, scope="group") == 0
    assert manager.check("ambient", group_id="100", user_id="2", seconds=10, scope="group") > 0
    assert manager.check("ambient", group_id="200", seconds=10, scope="group") == 0


def test_cooldown_reset():
    manager = CooldownManager()

    manager.check("meme", group_id="100", seconds=10, scope="group")
    manager.reset("meme", group_id="100", scope="group")

    assert manager.remaining("meme", group_id="100", scope="group") == 0
