from __future__ import annotations

from typing import Any

from src.chatbot.storage import JsonPluginStorage


store = JsonPluginStorage("points", default={"scopes": {}})


def get_points(scope: str, member_key: str) -> int:
    return int(_scope_data(scope).get("members", {}).get(member_key, {}).get("points", 0))


def add_points(scope: str, member_key: str, amount: int, *, reason: str = "") -> int:
    if amount < 0:
        return remove_points(scope, member_key, -amount, reason=reason)
    return _change_points(scope, member_key, amount, reason=reason)


def remove_points(scope: str, member_key: str, amount: int, *, reason: str = "") -> int:
    if amount < 0:
        return add_points(scope, member_key, -amount, reason=reason)
    current = get_points(scope, member_key)
    return _change_points(scope, member_key, -min(current, amount), reason=reason)


def transfer_points(scope: str, from_member: str, to_member: str, amount: int) -> tuple[bool, str]:
    if amount <= 0:
        return False, "数量必须是正整数。"
    if from_member == to_member:
        return False, "不能给自己转账。"
    if get_points(scope, from_member) < amount:
        return False, "积分不够。先去 /sign 攒一点吧。"

    def mutate(data: dict[str, Any]) -> None:
        members = data.setdefault("scopes", {}).setdefault(scope, {"members": {}}).setdefault(
            "members", {}
        )
        members.setdefault(from_member, {"points": 0})["points"] = (
            int(members[from_member].get("points", 0)) - amount
        )
        members.setdefault(to_member, {"points": 0})["points"] = (
            int(members[to_member].get("points", 0)) + amount
        )

    store.update(mutate)
    return True, "转账完成。"


def rank_points(scope: str, limit: int = 10) -> list[tuple[str, int]]:
    members = _scope_data(scope).get("members", {})
    rows = [(member_key, int(info.get("points", 0))) for member_key, info in members.items()]
    return sorted(rows, key=lambda item: item[1], reverse=True)[:limit]


def _change_points(scope: str, member_key: str, delta: int, *, reason: str = "") -> int:
    new_value = 0

    def mutate(data: dict[str, Any]) -> None:
        nonlocal new_value
        member = (
            data.setdefault("scopes", {})
            .setdefault(scope, {"members": {}})
            .setdefault("members", {})
            .setdefault(member_key, {"points": 0, "history": []})
        )
        new_value = max(0, int(member.get("points", 0)) + delta)
        member["points"] = new_value
        history = member.setdefault("history", [])
        history.append({"delta": delta, "reason": reason})
        del history[:-20]

    store.update(mutate)
    return new_value


def _scope_data(scope: str) -> dict[str, Any]:
    return store.read().get("scopes", {}).get(scope, {"members": {}})
