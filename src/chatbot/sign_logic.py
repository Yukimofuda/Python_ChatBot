from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any


BASE_REWARD = 10
MAX_STREAK_BONUS = 10
MAX_RANDOM_BONUS = 5


def sign_user(
    data: dict[str, Any],
    *,
    scope: str,
    user_id: str,
    today: date,
    rng: random.Random | None = None,
) -> tuple[dict[str, Any], bool, int]:
    rng = rng or random.Random()
    scopes = data.setdefault("scopes", {})
    users = scopes.setdefault(scope, {"users": {}}).setdefault("users", {})
    user = users.setdefault(
        user_id,
        {"total_days": 0, "streak_days": 0, "last_sign_date": "", "points": 0, "history": []},
    )
    today_text = today.isoformat()
    if user.get("last_sign_date") == today_text:
        return user, False, 0

    yesterday = (today - timedelta(days=1)).isoformat()
    streak = int(user.get("streak_days", 0)) + 1 if user.get("last_sign_date") == yesterday else 1
    reward = BASE_REWARD + min(streak - 1, MAX_STREAK_BONUS) + rng.randint(0, MAX_RANDOM_BONUS)
    user["streak_days"] = streak
    user["total_days"] = int(user.get("total_days", 0)) + 1
    user["last_sign_date"] = today_text
    user["points"] = int(user.get("points", 0)) + reward
    history = user.setdefault("history", [])
    history.append(today_text)
    del history[:-31]
    return user, True, reward


def calendar_text(history: list[str], *, today: date, days: int = 7) -> str:
    signed = set(history)
    labels = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        labels.append("签" if day.isoformat() in signed else "空")
    return " ".join(labels)
