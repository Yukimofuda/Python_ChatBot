from __future__ import annotations

import random
from datetime import date

from src.chatbot.persona_engine import daily_shift, normalize_mood

DAILY_PERSONAS = [
    ("困困工程师", "电量偏低，但 debug 判断还算准。"),
    ("吐槽役 JK", "吐槽欲上升，但无恶意。"),
    ("高冷观察员", "少说话，主要负责看穿配置问题。"),
    ("热血助教", "适合催大家先写一点。"),
    ("赛博诗人", "会把群聊看成第七数据层的像素雨。"),
    ("装傻天才", "明明懂，但会先欸一下。"),
    ("秋叶原黑客", "端口、adapter、日志，逐项排查。"),
    ("布丁守护者", "心情较好，精神热量充足。"),
    ("第七层住民", "对消息、命令和 WebSocket 很敏感。"),
    ("月读庭园观察员", "正在观察群梗浓度和精神状态。"),
]

MOOD_DEFAULTS = {
    "happy": 42,
    "tired": 18,
    "curiosity": 56,
    "snark": 38,
    "activity": 35,
    "quiet": 20,
    "wronged": 0,
}

AMBIENT_REPLIES = {
    "laugh": [
        "我在旁边观察了三秒，感觉这个群稳定地不稳定。",
        "这个笑点我先记下，感觉之后还会复发。",
    ],
    "help": [
        "先别急。先写最小的一步，人类经常能靠这一点骗过 deadline。",
        "好啦，呼吸一下。小栞在这边，不至于完全没救。",
    ],
    "hungry": [
        "赛博投喂：便利店布丁一份。精神热量看你信不信。",
        "好饿的话先找点吃的。空腹 debug 会让报错变凶。",
    ],
    "confused": [
        "欸？这串问号落到第七数据层的时候也迷路了一下。",
        "我也停顿了半秒。这个话题突然拐弯了吧。",
    ],
    "idle": [
        "第七数据层现在像凌晨便利店一样安静。",
        "我还醒着，只是刚刚在 404 号公寓发呆。",
    ],
    "slack": [
        "可以摆五分钟。五分钟后继续摆就叫正式停机维护了。",
        "开摆可以，但记得留一个进程负责收拾明天的你。",
    ],
}


def daily_persona(seed: str | None = None) -> tuple[str, str]:
    return daily_shift(seed or date.today().isoformat())


def mood_from_group_mood(group_mood: str) -> dict[str, int]:
    mood = normalize_mood(MOOD_DEFAULTS)
    if group_mood == "happy":
        mood["happy"] += 18
        mood["snark"] += 12
    elif group_mood == "angry":
        mood["tired"] += 25
        mood["quiet"] += 12
    elif group_mood == "active":
        mood["activity"] += 22
        mood["curiosity"] += 10
    elif group_mood == "confused":
        mood["curiosity"] += 20
    elif group_mood == "quiet":
        mood["quiet"] += 20
    return {key: min(100, max(0, value)) for key, value in mood.items()}


def choose_ambient_reply(kind: str) -> str:
    return random.choice(AMBIENT_REPLIES.get(kind, AMBIENT_REPLIES["idle"]))
