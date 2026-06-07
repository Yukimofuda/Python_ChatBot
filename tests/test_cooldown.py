from __future__ import annotations

from src.chatbot.cooldown import CooldownManager


def test_cooldown_returns_remaining_time():
    manager = CooldownManager()

    assert manager.check("fortune", actor_key="actor-a", seconds=10, scope="actor") == 0
    assert manager.check("fortune", actor_key="actor-a", seconds=10, scope="actor") > 0
    assert manager.check("fortune", actor_key="actor-b", seconds=10, scope="actor") == 0


def test_cooldown_group_scope_is_shared():
    manager = CooldownManager()

    assert manager.check("video", room_key="room-a", seconds=10, scope="room") == 0
    assert manager.check("video", room_key="room-a", actor_key="actor-b", seconds=10, scope="room") > 0
    assert manager.check("video", room_key="room-b", seconds=10, scope="room") == 0


def test_cooldown_reset():
    manager = CooldownManager()

    manager.check("sample", room_key="room-a", seconds=10, scope="room")
    manager.reset("sample", room_key="room-a", scope="room")

    assert manager.remaining("sample", room_key="room-a", scope="room") == 0
