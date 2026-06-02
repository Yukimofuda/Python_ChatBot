from __future__ import annotations

import random
from datetime import date
from typing import Any

from nonebot import on_command
from nonebot.adapters import Event
from nonebot.params import CommandArg

from src.chatbot.memory import scope_id
from src.chatbot.message_render import render_rank
from src.chatbot.permissions import get_user_id
from src.chatbot.points import add_points
from src.chatbot.sign_logic import calendar_text, sign_user
from src.chatbot.storage import JsonPluginStorage


store = JsonPluginStorage("sign", default={"scopes": {}})
sign = on_command("sign", aliases={"签到"}, priority=5, block=True)


@sign.handle()
async def handle_sign(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    scope = scope_id(event)
    user = get_user_id(event)
    if text == "info":
        await sign.finish(info_text(scope, user))
    if text == "rank":
        await sign.finish(rank_text(scope))
    if text == "calendar":
        await sign.finish(calendar(scope, user))
    if text:
        await sign.finish("用法：/sign、/sign info、/sign rank、/sign calendar")

    result: dict[str, Any] = {}
    created = False
    reward = 0

    def mutate(data: dict[str, Any]) -> None:
        nonlocal result, created, reward
        result, created, reward = sign_user(
            data,
            scope=scope,
            user_id=user,
            today=date.today(),
            rng=random.Random(f"{scope}:{user}:{date.today().isoformat()}"),
        )

    store.update(mutate)
    if created:
        total_points = add_points(scope, user, reward, reason="sign")
        await sign.finish(
            "\n".join(
                [
                    "签到成功！",
                    f"今日获得：{reward} 积分",
                    f"连续签到：{result['streak_days']} 天",
                    f"总签到：{result['total_days']} 天",
                    f"当前积分：{total_points}",
                ]
            )
        )
    await sign.finish(
        f"你今天已经签到过啦。\n连续签到：{result['streak_days']} 天\n当前积分：{result['points']}"
    )


def scope_data(scope: str) -> dict[str, Any]:
    return store.read().get("scopes", {}).get(scope, {"users": {}})


def info_text(scope: str, user_id: str) -> str:
    user = scope_data(scope).get("users", {}).get(user_id)
    if not user:
        return "你还没签到过。先来一发 /sign 吧。"
    return "\n".join(
        [
            "签到信息：",
            f"连续签到：{user.get('streak_days', 0)} 天",
            f"总签到：{user.get('total_days', 0)} 天",
            f"签到积分：{user.get('points', 0)}",
            f"上次签到：{user.get('last_sign_date', '无')}",
        ]
    )


def rank_text(scope: str) -> str:
    users = scope_data(scope).get("users", {})
    rows = sorted(
        ((user_id, int(info.get("points", 0))) for user_id, info in users.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if not rows:
        return "这个会话还没人签到。"
    return render_rank("签到积分榜", rows)


def calendar(scope: str, user_id: str) -> str:
    user = scope_data(scope).get("users", {}).get(user_id)
    if not user:
        return "还没有签到记录。"
    return f"最近 7 天：{calendar_text(user.get('history', []), today=date.today())}\n签=已签到，空=未签到"
