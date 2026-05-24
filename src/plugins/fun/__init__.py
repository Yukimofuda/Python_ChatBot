from __future__ import annotations

import random
from datetime import date

from nonebot import on_command
from nonebot.params import CommandArg


fortune = on_command("fortune", aliases={"今日运势", "运势"}, priority=5, block=True)
draw = on_command("draw", aliases={"抽签"}, priority=5, block=True)
eight_ball = on_command("8ball", aliases={"问问", "神谕"}, priority=5, block=True)
rate = on_command("rate", aliases={"打分"}, priority=5, block=True)
crazy = on_command("crazy", aliases={"发病"}, priority=5, block=True)

FORTUNES = [
    ("大吉", "Good day to start something new."),
    ("中吉", "Steady progress is favored today."),
    ("小吉", "Take a short break, then continue."),
    ("末吉", "Back up important files and be careful with unknown links."),
    ("凶", "Hydrate, restart if needed, and rest early."),
]
DRAW_ITEMS = ["大吉", "吉", "半吉", "小吉", "末吉", "凶", "大凶"]
ANSWERS = [
    "可以，甚至现在就可以。",
    "不太妙，建议先观望。",
    "Ask again later.",
    "概率很高，但需要一点运气。",
    "Not sure yet. Give it a moment.",
    "Looks promising.",
    "Wait a little and observe.",
]
CRAZY_TEMPLATES = [
    "{name}，没有你我可怎么活啊！",
    "Today's chat MVP is {name}.",
    "{name} joined; the room got more lively.",
    "Detected {name}; chat energy increased by 37%.",
    "{name}, thanks for keeping the chat alive.",
]


@fortune.handle()
async def handle_fortune() -> None:
    seed = date.today().isoformat()
    rng = random.Random(seed)
    level, text = rng.choice(FORTUNES)
    luck = rng.randint(1, 100)
    await fortune.finish(f"今日运势：{level}\n幸运值：{luck}/100\n{text}")


@draw.handle()
async def handle_draw(args=CommandArg()) -> None:
    topic = args.extract_plain_text().strip()
    prefix = f"{topic}：" if topic else "抽签结果："
    await draw.finish(prefix + random.choice(DRAW_ITEMS))


@eight_ball.handle()
async def handle_8ball(args=CommandArg()) -> None:
    question = args.extract_plain_text().strip()
    if not question:
        await eight_ball.finish("用法：/8ball 今天能准点下班吗")
    await eight_ball.finish(random.choice(ANSWERS))


@rate.handle()
async def handle_rate(args=CommandArg()) -> None:
    target = args.extract_plain_text().strip() or "这件事"
    score = random.randint(0, 100)
    comment = "离谱但合理" if score >= 85 else "还有上升空间" if score < 60 else "稳定发挥"
    await rate.finish(f"{target}：{score}/100，{comment}")


@crazy.handle()
async def handle_crazy(args=CommandArg()) -> None:
    name = args.extract_plain_text().strip() or "你"
    await crazy.finish(random.choice(CRAZY_TEMPLATES).format(name=name))
