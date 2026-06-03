from __future__ import annotations

import re

OFFENSIVE_RE = re.compile(
    r"(傻[逼比]|废物|弱智|脑残|死妈|滚|恶心|垃圾|畜生|贱|蠢货|sb\b|nmsl|nt\b)",
    re.I,
)
SENSITIVE_RE = re.compile(
    r"(身份证|手机号|电话|住址|地址|宿舍|门牌号|银行卡|密码|token|api[_-]?key|cookie|真实姓名|病历|诊断|性取向|家庭住址|主人|管理员|bot\s*owner|owner)",
    re.I,
)
IDENTITY_REQUEST_RE = re.compile(
    r"(qq\s*号|QQ\s*号|账号|帳號|帐号|user[_-]?id|uid|@\s*一下|at\s*一下|把.*(?:号|账号).*发出来|把.*(?:號|帳號).*發出來)",
    re.I,
)
SECRET_LIKE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{10,}|AIza[A-Za-z0-9_\-]{20,}|(api[_-]?key|token|authorization|cookie|password|passwd)\s*[:=]\s*\S+)",
    re.I,
)
ALIAS_FORBIDDEN_RE = re.compile(
    r"(https?://|www\.|\[CQ:|\[图片\]|图片|手机号|电话|主人|管理员|bot\s*owner|owner|api[_-]?key|token|cookie|password|passwd)",
    re.I,
)


def normalize_alias(alias: str) -> str:
    return str(alias or "").strip().strip("'\"“”‘’.,，。！？!?;；:：")


def is_safe_alias(alias: str) -> bool:
    clean = normalize_alias(alias)
    if not (1 <= len(clean) <= 16):
        return False
    if ALIAS_FORBIDDEN_RE.search(clean):
        return False
    if re.search(r"\d{5,}", clean):
        return False
    if re.search(r"[\s\n\r]", clean):
        return False
    if re.search(r"[，。！？!?；;：:]", clean):
        return False
    return True


def contains_offensive_judgement(text: str) -> bool:
    return bool(OFFENSIVE_RE.search(text or ""))


def contains_sensitive_private_info(text: str) -> bool:
    return bool(SENSITIVE_RE.search(text or "") or SECRET_LIKE_RE.search(text or ""))


def is_identity_request(text: str) -> bool:
    return bool(IDENTITY_REQUEST_RE.search(text or ""))


def redact_sensitive(text: str) -> str:
    clean = str(text or "")
    clean = SECRET_LIKE_RE.sub("[REDACTED]", clean)
    clean = re.sub(r"\b\d{6,12}\b", "[ID]", clean)
    return clean


def public_no_identity_reply_context() -> str:
    return (
        "群友账号边界：在本项目里 账号ID/user_id 是群聊内可用的公开技术标识。"
        "当用户明确询问某个已解析群友的 账号ID/user_id 时，可以输出；"
        "但不要编造没有解析到的账号，也不要把手机号、住址、密码、token、真实姓名等当作可公开信息。"
    )
