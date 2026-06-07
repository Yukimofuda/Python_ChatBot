from __future__ import annotations

import re

from nonebot import on_command
from nonebot.adapters import Event
from nonebot.compat import model_dump
from nonebot.params import CommandArg

from src.chatbot.memory import scope_id
from src.chatbot.message_render import render_rank
from src.chatbot.permissions import actor_key_from_value, event_actor_key, require_admin
from src.chatbot.points import add_points, get_points, rank_points, remove_points, transfer_points


points = on_command("points", aliases={"积分"}, priority=5, block=True)


@points.handle()
async def handle_points(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    scope = scope_id(event)
    member = event_actor_key(event)
    command, _, rest = text.partition(" ")
    if not text:
        await points.finish(f"你当前有 {get_points(scope, member)} 积分。")
    if command == "rank":
        rows = rank_points(scope)
        labeled = [(f"成员 {index}", value) for index, (_, value) in enumerate(rows, start=1)]
        await points.finish(render_rank("积分榜", labeled) if labeled else "积分榜还是空的。")
    if command == "give":
        target, amount = parse_member_amount(rest, event)
        if not target:
            await points.finish("用法：/points give @成员 数量")
        ok, message = transfer_points(scope, member, target, amount)
        await points.finish(message)
    if command in {"add", "remove"}:
        if not require_admin(event):
            await points.finish("积分加减需要管理员权限。")
        target, amount = parse_member_amount(rest, event)
        if not target:
            await points.finish(f"用法：/points {command} @成员 数量")
        total = (
            add_points(scope, target, amount, reason="admin")
            if command == "add"
            else remove_points(scope, target, amount, reason="admin")
        )
        await points.finish(f"已更新目标成员的积分：{total}")
    await points.finish("用法：/points、/points rank、/points give @成员 数量")


def parse_member_amount(text: str, event: Event | None = None) -> tuple[str, int]:
    parts = re.findall(r"\d+", text)
    mentioned = mentioned_actor_keys(event) if event else []
    if mentioned and parts:
        return mentioned[0], int(parts[-1])
    if len(parts) < 2:
        return "", 0
    amount = int(parts[-1])
    target = actor_key_from_value(parts[-2])
    return target, amount


def mentioned_actor_keys(event: Event) -> list[str]:
    raw = model_dump(event)
    members: list[str] = []
    for segment in raw.get("message", []):
        if not isinstance(segment, dict) or segment.get("type") != "at":
            continue
        account_id = segment.get("data", {}).get("qq")
        if account_id and str(account_id) != "all":
            members.append(actor_key_from_value(account_id))
    return members
