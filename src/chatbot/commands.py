from __future__ import annotations

from collections import OrderedDict


COMMANDS: "OrderedDict[str, list[str]]" = OrderedDict(
    [
        ("core", ["/ping", "/bot [分类]", "/about"]),
        ("utility", ["/echo 内容", "/calc 表达式", "/choose A | B", "/roll [面数]", "/time [时区]"]),
        ("fun", ["/fortune", "/draw [主题]", "/8ball 问题", "/rate 对象", "/crazy [名字]"]),
        ("admin", ["/status"]),
        ("bilibili", ["发送 B 站链接 - 自动解析 mp4", "/bili status", "/bili on|off", "/bili clean"]),
        ("sign", ["/sign", "/sign info", "/sign rank", "/sign calendar"]),
        ("points", ["/points", "/points rank", "/points give 用户ID 数量", "/points add 用户ID 数量", "/points remove 用户ID 数量"]),
        (
            "memory",
            [
                "/memory status",
                "/memory inspect <账号ID或昵称>",
                "/memory list <账号ID或昵称> [--all]",
                "/memory add <账号ID或昵称> <记忆内容> [#alias|#nickname|#profile]",
                "/memory edit <memory_id> <新内容>",
                "/memory delete <memory_id|账号ID 关键词>",
                "/memory restore <memory_id>",
                "/memory audit [memory_id|账号ID]",
            ],
        ),
    ]
)

ALIASES = {
    "all": "all",
    "bili": "bilibili",
    "help": "core",
    "bothelp": "core",
    "bot_help": "core",
    "memory_crud": "memory",
    "social_memory": "memory",
    "签到": "sign",
    "积分": "points",
}
