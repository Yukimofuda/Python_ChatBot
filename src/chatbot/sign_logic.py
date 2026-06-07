from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any


BASE_REWARD = 10
MAX_STREAK_BONUS = 10
MAX_RANDOM_BONUS = 5


def sign_member(
    data: dict[str, Any],
    *,
    scope: str,
    member_key: str,
    today: date,
    rng: random.Random | None = None,
) -> tuple[dict[str, Any], bool, int]:
    rng = rng or random.Random()
    scopes = data.setdefault("scopes", {})
    members = scopes.setdefault(scope, {"members": {}}).setdefault("members", {})
    member = members.setdefault(
        member_key,
        {"total_days": 0, "streak_days": 0, "last_sign_date": "", "points": 0, "history": []},
    )
    today_text = today.isoformat()
    if member.get("last_sign_date") == today_text:
        return member, False, 0

    yesterday = (today - timedelta(days=1)).isoformat()
    streak = int(member.get("streak_days", 0)) + 1 if member.get("last_sign_date") == yesterday else 1
    reward = BASE_REWARD + min(streak - 1, MAX_STREAK_BONUS) + rng.randint(0, MAX_RANDOM_BONUS)
    member["streak_days"] = streak
    member["total_days"] = int(member.get("total_days", 0)) + 1
    member["last_sign_date"] = today_text
    member["points"] = int(member.get("points", 0)) + reward
    history = member.setdefault("history", [])
    history.append(today_text)
    del history[:-31]
    return member, True, reward


def calendar_text(history: list[str], *, today: date, days: int = 7) -> str:
    signed = set(history)
    labels = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        labels.append("签" if day.isoformat() in signed else "空")
    return " ".join(labels)
