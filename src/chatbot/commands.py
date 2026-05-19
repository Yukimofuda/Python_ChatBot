from __future__ import annotations

from collections import OrderedDict


COMMANDS: "OrderedDict[str, list[str]]" = OrderedDict(
    [
        ("core", ["/ping", "/shion [分类]", "/about"]),
        ("utility", ["/echo 内容", "/calc 表达式", "/choose A | B", "/roll [面数]", "/time [时区]"]),
        ("fun", ["/fortune", "/draw [主题]", "/8ball 问题", "/rate 对象", "/crazy [名字]"]),
        ("admin", ["/status"]),
        ("bilibili", ["发送 B 站链接 - 自动解析 mp4", "/bili status", "/bili on|off", "/bili clean"]),
        ("sign", ["/sign", "/sign info", "/sign rank", "/sign calendar"]),
        ("points", ["/points", "/points rank", "/points give 用户ID 数量", "/points add 用户ID 数量", "/points remove 用户ID 数量"]),
        (
            "persona",
            [
                "/persona",
                "/persona today",
                "/persona mood",
                "/persona profile",
                "/persona world",
                "/persona rules",
                "/persona style",
                "/persona memory",
                "/persona on|off",
                "/persona set 内容",
                "/persona reset",
            ],
        ),
        (
            "meme",
            ["/meme add 梗名 解释", "/meme list", "/meme search 关键词", "/meme random", "/meme stats", "/meme on|off", "/meme del 编号"],
        ),
        ("ambient", ["/ambient on|off", "/ambient status", "/ambient level 低|中|高", "/ambient test"]),
        ("dream", ["/dream", "/dream today", "/dream write 内容", "/dream random", "/dream history", "/dream on|off"]),
        ("mfortune", ["/mfortune", "/mfortune group"]),
    ]
)

ALIASES = {
    "bili": "bilibili",
    "shionhelp": "core",
    "shion_help": "core",
    "memory_fortune": "mfortune",
    "签到": "sign",
    "积分": "points",
    "persona_live": "persona",
    "meme_memory": "meme",
    "ambient_reply": "ambient",
    "dream_diary": "dream",
}
