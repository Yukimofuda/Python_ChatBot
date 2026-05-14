from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nonebot import on_command
from nonebot.params import CommandArg

from src.chatbot.safe_math import safe_eval
from src.chatbot.settings import get_settings


settings = get_settings()

echo = on_command("echo", aliases={"复读"}, priority=5, block=True)
calc = on_command("calc", aliases={"计算"}, priority=5, block=True)
choose = on_command("choose", aliases={"选择"}, priority=5, block=True)
roll = on_command("roll", aliases={"骰子"}, priority=5, block=True)
time_cmd = on_command("time", aliases={"时间"}, priority=5, block=True)


@echo.handle()
async def handle_echo(args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    await echo.finish(text or "请在 /echo 后面加上要复读的内容。")


@calc.handle()
async def handle_calc(args=CommandArg()) -> None:
    if not settings.enable_calc:
        await calc.finish("计算功能当前未开启。")

    expression = args.extract_plain_text().strip()
    if not expression:
        await calc.finish("用法：/calc 1 + 2 * (3 + 4)")

    try:
        result = safe_eval(expression)
    except Exception as exc:
        await calc.finish(f"无法计算：{exc}")

    await calc.finish(f"{expression} = {result}")


@choose.handle()
async def handle_choose(args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    options = [item.strip() for item in text.replace("，", "|").split("|") if item.strip()]
    if len(options) < 2:
        await choose.finish("用法：/choose 方案 A | 方案 B | 方案 C")
    await choose.finish(random.choice(options))


@roll.handle()
async def handle_roll(args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    sides = 100
    if text:
        try:
            sides = int(text)
        except ValueError:
            await roll.finish("骰子面数需要是整数，例如 /roll 20。")
    if sides < 2 or sides > 1_000_000:
        await roll.finish("骰子面数需要在 2 到 1000000 之间。")
    await roll.finish(f"d{sides}: {random.randint(1, sides)}")


@time_cmd.handle()
async def handle_time(args=CommandArg()) -> None:
    timezone = args.extract_plain_text().strip() or "Asia/Shanghai"
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        await time_cmd.finish("找不到这个时区，例如可以使用 Asia/Shanghai 或 UTC。")
    await time_cmd.finish(now.strftime(f"{timezone}: %Y-%m-%d %H:%M:%S"))
