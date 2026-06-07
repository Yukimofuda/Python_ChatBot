from __future__ import annotations

import random
from datetime import date
from typing import Any

from nonebot import on_command
from nonebot.adapters import Event
from nonebot.params import CommandArg

from src.chatbot.memory import scope_id
from src.chatbot.message_render import render_rank
from src.chatbot.permissions import event_actor_key
from src.chatbot.points import add_points
from src.chatbot.sign_logic import calendar_text, sign_member
from src.chatbot.storage import JsonPluginStorage


store = JsonPluginStorage("sign", default={"scopes": {}})
sign = on_command("sign", aliases={"签到"}, priority=5, block=True)


@sign.handle()
async def handle_sign(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    scope = scope_id(event)
    member = event_actor_key(event)
    if text == "info":
        await sign.finish(info_text(scope, member))
    if text == "rank":
        await sign.finish(rank_text(scope))
    if text == "calendar":
        await sign.finish(calendar(scope, member))
    if text:
        await sign.finish("用法：/sign、/sign info、/sign rank、/sign calendar")

    result: dict[str, Any] = {}
    created = False
    reward = 0

    def mutate(data: dict[str, Any]) -> None:
        nonlocal result, created, reward
        result, created, reward = sign_member(
            data,
            scope=scope,
            member_key=member,
            today=date.today(),
            rng=random.Random(f"{scope}:{member}:{date.today().isoformat()}"),
        )

    store.update(mutate)
    if created:
        total_points = add_points(scope, member, reward, reason="sign")
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
    return store.read().get("scopes", {}).get(scope, {"members": {}})


def info_text(scope: str, member_key: str) -> str:
    member = scope_data(scope).get("members", {}).get(member_key)
    if not member:
        return "你还没签到过。先来一发 /sign 吧。"
    return "\n".join(
        [
            "签到信息：",
            f"连续签到：{member.get('streak_days', 0)} 天",
            f"总签到：{member.get('total_days', 0)} 天",
            f"签到积分：{member.get('points', 0)}",
            f"上次签到：{member.get('last_sign_date', '无')}",
        ]
    )


def rank_text(scope: str) -> str:
    members = scope_data(scope).get("members", {})
    rows = sorted(
        ((member_key, int(info.get("points", 0))) for member_key, info in members.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if not rows:
        return "这个会话还没人签到。"
    labeled = [(f"成员 {index}", value) for index, (_, value) in enumerate(rows, start=1)]
    return render_rank("签到积分榜", labeled)


def calendar(scope: str, member_key: str) -> str:
    member = scope_data(scope).get("members", {}).get(member_key)
    if not member:
        return "还没有签到记录。"
    return f"最近 7 天：{calendar_text(member.get('history', []), today=date.today())}\n签=已签到，空=未签到"
