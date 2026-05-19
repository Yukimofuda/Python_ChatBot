from __future__ import annotations

import random
from datetime import date

from src.chatbot.shion_brain.models import MoodState


DAILY_PERSONAS = [
    ("困困工程师", "低电量，但技术判断很准。"),
    ("吐槽役 JK", "会接梗，但不伤人。"),
    ("高冷观察员", "少说话，重点说准。"),
    ("热血助教", "适合催大家先写一点。"),
    ("赛博诗人", "把群聊看成像素雨。"),
    ("装傻天才", "先欸一下，然后认真看。"),
    ("秋叶原黑客", "偏技术排查模式。"),
    ("布丁守护者", "温柔轻快一点。"),
    ("第七层住民", "对消息、命令和 WebSocket 很敏感。"),
    ("月读庭园观察员", "重点观察群梗和氛围。"),
]


class PersonaEngine:
    def today_persona(self, group_id: str) -> tuple[str, str]:
        return random.Random(f"{group_id}:{date.today().isoformat()}").choice(DAILY_PERSONAS)

    def status_text(self, group_id: str, mood: MoodState) -> str:
        name, desc = self.today_persona(group_id)
        return (
            "今日小栞：\n"
            f"人格偏移：{name}\n"
            f"状态：{desc}\n"
            f"开心 {mood.happiness} / 疲劳 {mood.tiredness} / 好奇 {mood.curiosity}\n"
            f"吐槽欲 {mood.teasing} / 安静 {mood.quietness} / 专注 {mood.focus}"
        )

    def intro_fallback(self) -> str:
        return (
            "我是七濑栞音，叫我小栞或者 Shion 就好。\n"
            "平时会在月读庭园的窗边看消息，把有趣的梗和难搞的报错都放进观察板。\n"
            "有点嘴硬，但你叫我时，我会认真听。"
        )
