from __future__ import annotations

from collections import OrderedDict


COMMANDS: "OrderedDict[str, list[str]]" = OrderedDict(
    [
        ("core", ["/ping", "/cbhelp [category]", "/about"]),
        ("utility", ["/echo content", "/calc expression", "/choose A | B", "/roll [sides]", "/time [timezone]"]),
        ("fun", ["/fortune", "/draw [topic]", "/8ball question", "/rate target", "/crazy name"]),
        ("admin", ["/status"]),
        ("bilibili", ["Send a Bilibili URL", "/bili status", "/bili on|off", "/bili clean"]),
        ("sign", ["/sign", "/sign info", "/sign rank", "/sign calendar"]),
        ("points", ["/points", "/points rank", "/points give USER_ID amount", "/points add USER_ID amount", "/points remove USER_ID amount"]),
    ]
)

ALIASES = {
    "all": "all",
    "help": "core",
    "bothelp": "core",
    "bili": "bilibili",
    "签到": "sign",
    "积分": "points",
}
