from __future__ import annotations

import random
from datetime import date

from nonebot import on_command
from nonebot.adapters import Event

from src.chatbot.memory import group_snapshot, scope_id, user_snapshot
from src.chatbot.permissions import get_user_id
from src.chatbot.random_personality import daily_persona


mfortune = on_command("mfortune", aliases={"记忆运势"}, priority=5, block=True)


@mfortune.handle()
async def handle_mfortune(event: Event) -> None:
    group = scope_id(event)
    user = get_user_id(event)
    snapshot = group_snapshot(group)
    personal = user_snapshot(group, user)
    persona_name, _ = daily_persona(f"{group}:{date.today().isoformat()}")
    rng = random.Random(f"{date.today().isoformat()}:{group}:{user}")
    words = [word for word, _ in personal["top_keywords"]] or [word for word, _ in snapshot["top_keywords"]] or ["先写一点"]
    keyword = rng.choice(words)
    score = rng.randint(1, 100)
    await mfortune.finish(
        "\n".join(
            [
                "你的记忆型运势：",
                f"今日关键词：{keyword}",
                f"幸运指数：{score}",
                f"群聊氛围：{snapshot['mood']}",
                f"今日小栞人格：{persona_name}",
                "今日宜：把任务拆成最小的一步",
                "今日忌：打开 B 站后说“我就看 5 分钟”",
                "小栞吐槽：我不信你只看 5 分钟，但我愿意假装相信。",
            ]
        )
    )
