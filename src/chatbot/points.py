from __future__ import annotations

from typing import Any

from src.chatbot.storage import JsonPluginStorage


store = JsonPluginStorage("points", default={"scopes": {}})


def get_points(scope: str, user_id: str) -> int:
    return int(_scope_data(scope).get("users", {}).get(user_id, {}).get("points", 0))


def add_points(scope: str, user_id: str, amount: int, *, reason: str = "") -> int:
    if amount < 0:
        return remove_points(scope, user_id, -amount, reason=reason)
    return _change_points(scope, user_id, amount, reason=reason)


def remove_points(scope: str, user_id: str, amount: int, *, reason: str = "") -> int:
    if amount < 0:
        return add_points(scope, user_id, -amount, reason=reason)
    current = get_points(scope, user_id)
    return _change_points(scope, user_id, -min(current, amount), reason=reason)


def transfer_points(scope: str, from_user: str, to_user: str, amount: int) -> tuple[bool, str]:
    if amount <= 0:
        return False, "数量必须是正整数。"
    if from_user == to_user:
        return False, "不能给自己转账。"
    if get_points(scope, from_user) < amount:
        return False, "积分不够。先去 /sign 攒一点吧。"

    def mutate(data: dict[str, Any]) -> None:
        users = data.setdefault("scopes", {}).setdefault(scope, {"users": {}}).setdefault("users", {})
        users.setdefault(from_user, {"points": 0})["points"] = int(users[from_user].get("points", 0)) - amount
        users.setdefault(to_user, {"points": 0})["points"] = int(users[to_user].get("points", 0)) + amount

    store.update(mutate)
    return True, "转账完成。"


def rank_points(scope: str, limit: int = 10) -> list[tuple[str, int]]:
    users = _scope_data(scope).get("users", {})
    rows = [(user_id, int(info.get("points", 0))) for user_id, info in users.items()]
    return sorted(rows, key=lambda item: item[1], reverse=True)[:limit]


def _change_points(scope: str, user_id: str, delta: int, *, reason: str = "") -> int:
    new_value = 0

    def mutate(data: dict[str, Any]) -> None:
        nonlocal new_value
        user = (
            data.setdefault("scopes", {})
            .setdefault(scope, {"users": {}})
            .setdefault("users", {})
            .setdefault(user_id, {"points": 0, "history": []})
        )
        new_value = max(0, int(user.get("points", 0)) + delta)
        user["points"] = new_value
        history = user.setdefault("history", [])
        history.append({"delta": delta, "reason": reason})
        del history[:-20]

    store.update(mutate)
    return new_value


def _scope_data(scope: str) -> dict[str, Any]:
    return store.read().get("scopes", {}).get(scope, {"users": {}})
