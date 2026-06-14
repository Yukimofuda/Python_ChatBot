from __future__ import annotations

import re

from nonebot import on_command
from nonebot.adapters import Event
from nonebot.compat import model_dump
from nonebot.params import CommandArg

from src.chatbot.memory import scope_id
from src.chatbot.message_render import render_rank
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.points import add_points, get_points, rank_points, remove_points, transfer_points


points = on_command("points", aliases={"积分"}, priority=5, block=True)


@points.handle()
async def handle_points(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    scope = scope_id(event)
    user = get_user_id(event)
    command, _, rest = text.partition(" ")
    if not text:
        await points.finish(f"你当前有 {get_points(scope, user)} 积分。")
    if command == "rank":
        rows = rank_points(scope)
        await points.finish(render_rank("积分榜", rows) if rows else "积分榜还是空的。")
    if command == "give":
        target, amount = parse_user_amount(rest, event)
        if not target:
            await points.finish("用法：/points give @用户 数量，或 /points give 用户ID 数量")
        ok, message = transfer_points(scope, user, target, amount)
        await points.finish(message)
    if command in {"add", "remove"}:
        if not require_admin(event):
            await points.finish("积分加减需要管理员权限。")
        target, amount = parse_user_amount(rest, event)
        if not target:
            await points.finish(f"用法：/points {command} 用户ID 数量")
        total = (
            add_points(scope, target, amount, reason="admin")
            if command == "add"
            else remove_points(scope, target, amount, reason="admin")
        )
        await points.finish(f"已更新 {target} 的积分：{total}")
    await points.finish("用法：/points、/points rank、/points give 用户ID 数量")


def parse_user_amount(text: str, event: Event | None = None) -> tuple[str, int]:
    parts = re.findall(r"\d+", text)
    mentioned = mentioned_user_ids(event) if event else []
    if mentioned and parts:
        return mentioned[0], int(parts[-1])
    if len(parts) < 2:
        return "", 0
    amount = int(parts[-1])
    target = parts[-2]
    return target, amount


def mentioned_user_ids(event: Event) -> list[str]:
    raw = model_dump(event)
    users: list[str] = []
    for segment in raw.get("message", []):
        if not isinstance(segment, dict) or segment.get("type") != "at":
            continue
        qq = segment.get("data", {}).get("qq")
        if qq and str(qq) != "all":
            users.append(str(qq))
    return users
