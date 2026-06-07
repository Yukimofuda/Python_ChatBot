from __future__ import annotations

from collections import OrderedDict


COMMANDS: "OrderedDict[str, list[str]]" = OrderedDict(
    [
        ("core", ["/ping", "/bot [分类]", "/about"]),
        ("utility", ["/echo 内容", "/calc 表达式", "/choose A | B", "/roll [面数]", "/time [时区]"]),
        ("fun", ["/fortune", "/draw [主题]", "/8ball 问题", "/rate 对象", "/crazy [名字]"]),
        ("admin", ["/status"]),
        ("bilibili", ["发送 B 站链接或卡片文本", "/bili status", "/bili on|off", "/bili clean"]),
        ("sign", ["/sign", "/sign info", "/sign rank", "/sign calendar"]),
        ("points", ["/points", "/points rank", "/points give @成员 数量", "/points add @成员 数量", "/points remove @成员 数量"]),
    ]
)

ALIASES = {
    "bili": "bilibili",
    "help": "core",
    "bothelp": "core",
    "bot_help": "core",
    "签到": "sign",
    "积分": "points",
}
