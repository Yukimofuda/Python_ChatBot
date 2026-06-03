from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SYSTEM_EXPOSURE_TERMS = (
    "管理员确认", "管理员那边", "管理员说", "数据库", "系统记录", "后台", "检索结果", "检索",
    "记录显示", "我这边只有记录", "我这里只有记录", "可靠记录", "可靠信息", "观测记录",
    "内部记录", "后台记录", "审计", "migration", "source_type", "confidence",
    "ResolvedTargetUserId", "ProfileQueryAnswerContract", "AnswerObligation", "群友认知参考",
)
SYSTEM_EXPOSURE_RE = re.compile("|".join(re.escape(x) for x in SYSTEM_EXPOSURE_TERMS), re.I)

PROFILE_QUERY_RE = re.compile(
    r"(是谁|哪个群友|哪个人|哪位|是怎样的人|怎么样|怎样的人|什么样|你记得.*吗|记得.*吗|评价一下|印象|说说|描述一下|了解.*吗)"
)
SELF_QUERY_RE = re.compile(r"(我是谁|你记得我吗|记得我吗|我是什么人|我怎么样|你认识我吗)")
PRONOUN_QUERY_RE = re.compile(r"(他是谁|她是谁|ta是谁|TA是谁|这个人是谁|这人是谁|他怎么样|她怎么样|这个人怎么样|这人怎么样|回复.*是谁|刚才.*是谁|上面.*是谁)")
QUESTION_SUFFIX_RE = re.compile(
    r"(是谁|哪个群友|哪个人|哪位|是怎样的人|怎么样|怎样的人|什么样的人|什么样|你记得|记得|评价|印象|说说|描述|账号ID|qq号|user[_-]?id|uid|多少|多少号|号码|账号|帐号|，|,|。|？|\?|！|!)",
    re.I,
)
REPLY_PREVIEW_RE = re.compile(r"\[回复消息\s*\[([^\](]{1,40})\((\d{5,12})\)\]\s*([^\]]{0,300})", re.S)
CQ_REPLY_RE = re.compile(r"\[CQ:reply,id=([^,\]]+)")


def normalize_reference(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"\[CQ:[^\]]+\]", " ", text)
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff_\-]+", "", text)
    return text.strip()


def is_profile_like_query(text: str) -> bool:
    return bool(PROFILE_QUERY_RE.search(str(text or "")))


def is_self_query(text: str) -> bool:
    return bool(SELF_QUERY_RE.search(str(text or "")))


def is_pronoun_or_reply_query(text: str) -> bool:
    return bool(PRONOUN_QUERY_RE.search(str(text or "")))


def extract_reference_terms(text: str) -> list[str]:
    raw = str(text or "")
    raw = REPLY_PREVIEW_RE.sub(" ", raw)
    raw = re.sub(r"\[CQ:[^\]]+\]", " ", raw)
    raw = re.sub(r"@\d{5,12}", " ", raw)
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return []
    parts = [p for p in re.split(QUESTION_SUFFIX_RE, compact) if p and not QUESTION_SUFFIX_RE.fullmatch(p)]
    refs: list[str] = []
    for part in parts:
        candidate = part.strip("的他她它这个人这个群友")
        if 1 <= len(candidate) <= 24 and not re.fullmatch(r"\d+", candidate):
            refs.append(candidate)
    if not refs and 1 <= len(compact) <= 24:
        refs.append(compact)
    return list(dict.fromkeys(refs))[:5]


def extract_reply_metadata(raw: dict[str, Any] | None = None, *, text: str = "", raw_message_text: str = "") -> dict[str, Any]:
    raw = raw or {}
    features: dict[str, Any] = {}
    message = raw.get("message") or []
    if isinstance(message, list):
        for seg in message:
            if not isinstance(seg, dict) or seg.get("type") != "reply":
                continue
            data = seg.get("data") or {}
            reply_id = str(data.get("id") or data.get("message_id") or "").strip()
            if reply_id:
                features["reply_to_message_id"] = reply_id
            # Some adapters include sender/content on reply segments; keep it if present.
            sender_id = str(data.get("user_id") or data.get("sender_id") or data.get("qq") or "").strip()
            if sender_id:
                features["reply_sender_id"] = sender_id
            sender_name = str(data.get("nickname") or data.get("card") or data.get("name") or "").strip()
            if sender_name:
                features["reply_sender_name"] = sender_name
            content = str(data.get("text") or data.get("content") or data.get("message") or "").strip()
            if content:
                features["reply_text"] = content[:500]
            break
    merged = "\n".join([str(raw_message_text or ""), str(text or "")])
    m = REPLY_PREVIEW_RE.search(merged)
    if m:
        features.setdefault("reply_sender_name", m.group(1).strip())
        features.setdefault("reply_sender_id", m.group(2).strip())
        content = re.sub(r"\s+", " ", m.group(3) or "").strip()
        if content:
            features.setdefault("reply_text", content[:500])
    cq = CQ_REPLY_RE.search(merged)
    if cq:
        features.setdefault("reply_to_message_id", cq.group(1).strip())
    return features


def naturalize_memory_text(text: str) -> str:
    line = re.sub(r"\s+", " ", str(text or "")).strip()
    if not line:
        return ""
    line = re.sub(r"管理员确认该?群友被称作[：:]?", "通常被叫作", line)
    line = re.sub(r"管理员确认这个人被称作[：:]?", "通常被叫作", line)
    line = re.sub(r"该?群友自述[：:]?", "自己说过：", line)
    line = line.replace("该群友", "这个人").replace("这个群友", "这个人")
    for token in SYSTEM_EXPOSURE_TERMS:
        line = line.replace(token, "")
    line = re.sub(r"\s+", " ", line).strip(" ，,。")
    if not line:
        return ""
    return line + ("" if line.endswith(("。", "！", "？")) else "。")


def clean_persona_context(text: str) -> str:
    clean = str(text or "")
    for token in SYSTEM_EXPOSURE_TERMS:
        clean = clean.replace(token, "")
    clean = clean.replace("不要提来源、系统、或字段。", "")
    clean = clean.replace("不要提来源、系统、后台或字段。", "")
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def scan_alias_targets(store: Any, text: str, *, scope_id: str | None = None, limit: int = 3) -> list[str]:
    refs = extract_reference_terms(text)
    ref_norms = [normalize_reference(r) for r in refs if normalize_reference(r)]
    if not ref_norms:
        return []
    found: list[str] = []
    try:
        with store.connect() as conn:
            try:
                user_rows = conn.execute("SELECT user_id, display_name, aliases_json FROM social_users").fetchall()
            except Exception:
                user_rows = []
            try:
                mem_rows = conn.execute(
                    """
                    SELECT subject_user_id, memory_text, tags_json, confidence, priority, updated_at
                    FROM social_memories
                    WHERE is_active=1 AND confidence>=0.2
                    ORDER BY (priority * 0.45 + confidence * 0.45) DESC, updated_at DESC
                    LIMIT 800
                    """
                ).fetchall()
            except Exception:
                mem_rows = []
    except Exception:
        return []
    import json
    for row in user_rows:
        aliases: list[str] = []
        try:
            aliases.append(str(row["display_name"] or ""))
            aliases.extend(json.loads(row["aliases_json"] or "[]"))
        except Exception:
            pass
        for alias in aliases:
            alias_norm = normalize_reference(alias)
            if alias_norm and any(rn == alias_norm or (len(rn) >= 2 and rn in alias_norm) for rn in ref_norms):
                found.append(str(row["user_id"]))
                break
    for row in mem_rows:
        try:
            mem_norm = normalize_reference(row["memory_text"])
            uid = str(row["subject_user_id"])
        except Exception:
            continue
        if mem_norm and any(len(rn) >= 2 and rn in mem_norm for rn in ref_norms):
            found.append(uid)
    return list(dict.fromkeys(found))[:limit]


def recent_context_lines(store: Any, scope_id: str, *, limit: int = 2) -> list[str]:
    if not scope_id:
        return []
    try:
        with store.connect() as conn:
            rows = conn.execute(
                """
                SELECT sender_user_id, message_text, created_at
                FROM social_interactions
                WHERE scope_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(scope_id), int(limit)),
            ).fetchall()
    except Exception:
        return []
    lines: list[str] = []
    for row in reversed(rows):
        try:
            sender = str(row["sender_user_id"] or "")
            msg = re.sub(r"\s+", " ", str(row["message_text"] or "")).strip()
        except Exception:
            continue
        if msg:
            lines.append(f"{sender}: {msg[:120]}")
    return lines
