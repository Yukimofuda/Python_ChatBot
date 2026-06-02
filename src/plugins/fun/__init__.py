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
    ("大吉", "适合开新坑、发怪图、把 TODO 变成 done。"),
    ("中吉", "适合稳扎稳打，少和奇怪报错硬碰硬。"),
    ("小吉", "适合摸一会儿再干活，效率反而更高。"),
    ("末吉", "适合备份文件，谨慎点击来路不明的按钮。"),
    ("凶", "适合喝水、重启、早点睡。"),
]
DRAW_ITEMS = ["大吉", "吉", "半吉", "小吉", "末吉", "凶", "大凶"]
ANSWERS = [
    "可以，甚至现在就可以。",
    "不太妙，建议先观望。",
    "命运说：再问就是加班。",
    "概率很高，但需要一点运气。",
    "别急，答案正在加载。",
    "会赢的。",
    "先别动，让事情自己暴露。",
]
CRAZY_TEMPLATES = [
    "{name}，没有你我可怎么活啊！",
    "我宣布今天的群聊 MVP 是 {name}。",
    "{name} 一出现，CPU 风扇都开始鼓掌。",
    "检测到 {name}，群聊含糖量上升 37%。",
    "{name}，你是这片赛博荒原里唯一的补给站。",
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
