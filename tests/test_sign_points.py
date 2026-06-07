from __future__ import annotations

import random
from datetime import date, timedelta

from src.chatbot.sign_logic import calendar_text, sign_member


def test_sign_user_first_day():
    data = {}
    user, created, reward = sign_member(
        data,
        scope="group:1",
        member_key="actor-a",
        today=date(2026, 5, 16),
        rng=random.Random(1),
    )

    assert created is True
    assert reward >= 10
    assert user["total_days"] == 1
    assert user["streak_days"] == 1


def test_sign_user_same_day_is_rejected():
    data = {}
    today = date(2026, 5, 16)
    sign_member(data, scope="group:1", member_key="actor-a", today=today, rng=random.Random(1))
    user, created, reward = sign_member(
        data,
        scope="group:1",
        member_key="actor-a",
        today=today,
        rng=random.Random(2),
    )

    assert created is False
    assert reward == 0
    assert user["total_days"] == 1


def test_sign_user_continuous_streak():
    data = {}
    today = date(2026, 5, 16)
    sign_member(data, scope="group:1", member_key="actor-a", today=today - timedelta(days=1))
    user, created, _ = sign_member(data, scope="group:1", member_key="actor-a", today=today)

    assert created is True
    assert user["streak_days"] == 2


def test_calendar_text():
    today = date(2026, 5, 16)
    history = ["2026-05-14", "2026-05-16"]

    assert calendar_text(history, today=today, days=3) == "签 空 签"
