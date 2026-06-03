from __future__ import annotations

"""Operator-facing social memory tasks.

v29 invariant:
- /memory add/list/edit/delete/restore/audit are all backed by SocialMemoryCrud.
- legacy /memory commands and natural-language @bot operations use the same CRUD/governance path.
- delete by term only soft-deletes matching rows; whole-user wipe requires --all --confirm.
- replies avoid forced database/admin wording.
"""

import json
import re
from typing import Any

from .store import SocialCognitionStore, social_cognition_store
from .memory_crud import (
    SocialMemoryCrud,
    ensure_crud_tables,
    utc_now,
    _audit,
    _revision,
    _row_to_dict,
)

MEMORY_ID_RE = re.compile(r"\b(smem_[a-f0-9]{12,64}|[a-f0-9]{24,64})\b", re.I)
QUOTE_RE = re.compile(r"[“\"']([^”\"']{1,160})[”\"']")
TAG_RE = re.compile(r"#([A-Za-z_\-\u4e00-\u9fff]{1,32})")
FORBIDDEN_STYLE_RE = re.compile(r"(我这边|管理员|高可信|数据库|审计|source|trust|raw|profile_summary|系统记录)", re.I)

TAG_ALIASES = {
    "别名": "alias",
    "称呼": "alias",
    "昵称": "nickname",
    "画像": "profile",
    "印象": "profile",
    "技能": "skill",
    "偏好": "preference",
    "习惯": "habit",
}


def _normalize_cli_flags(text: str) -> str:
    # Users often type an em dash from mobile IME: —all. Normalize it to --all.
    return str(text or "").replace("——", "--").replace("—", "--").replace("－", "-").replace("–", "-")


def _clean(text: str) -> str:
    text = str(text or "")
    # Normalize mobile/IME punctuation and invisible chars that often appear in QQ messages.
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", _normalize_cli_flags(text)).strip(" \t\r\n，,。.;；：:")


def _normalize_subject_ref(ref: str) -> str:
    raw = _clean(ref)
    if not raw:
        return ""
    # Accept CQ at segments, plain @QQ, full-width digits and accidental punctuation around QQ IDs.
    fw = str.maketrans("０１２３４５６７８９", "0123456789")
    raw = raw.translate(fw)
    m = re.search(r"\[CQ:at,qq=(\d{5,12})\]", raw)
    if m:
        return m.group(1)
    m = re.search(r"@\s*(\d{5,12})", raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{5,12}", raw):
        return raw
    # If a account id is the only numeric target embedded in noisy command text, use it.
    nums = re.findall(r"(?<!\d)(\d{5,12})(?!\d)", raw)
    if len(nums) == 1:
        return nums[0]
    return raw


def _safe(text: str) -> str:
    # Keep user-facing punctuation; _clean() intentionally strips command
    # punctuation, so formatter output should not be passed through that trim.
    raw = str(text or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    raw = _normalize_cli_flags(raw)
    out = FORBIDDEN_STYLE_RE.sub("", raw)
    out = re.sub(r"[ \t\r\n]+", " ", out).strip(" \t\r\n")
    return out or "完成。"


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _extract_tags(text: str, *, default: str = "profile") -> tuple[str, str]:
    tags = [TAG_ALIASES.get(t.casefold(), TAG_ALIASES.get(t, t.casefold())) for t in TAG_RE.findall(text or "")]
    stripped = TAG_RE.sub(" ", text or "")
    stripped = _clean(stripped)
    return stripped, ",".join(tags) if tags else default


def _split_ref_and_text(rest: str) -> tuple[str, str]:
    raw = _clean(rest)
    if not raw:
        return "", ""
    if "：" in raw:
        left, right = raw.split("：", 1)
        left = _clean(left)
        right = _clean(right)
        parts = left.split()
        return (_normalize_subject_ref(parts[0]) if parts else ""), right
    if ":" in raw:
        left, right = raw.split(":", 1)
        left = _clean(left)
        right = _clean(right)
        parts = left.split()
        return (_normalize_subject_ref(parts[0]) if parts else ""), right
    parts = raw.split(maxsplit=1)
    if len(parts) == 1:
        return _normalize_subject_ref(parts[0]), ""
    return _normalize_subject_ref(parts[0]), _clean(parts[1])


def _split_ref_and_term(rest: str) -> tuple[str, str]:
    raw = _clean(rest)
    if not raw:
        return "", ""
    quoted = [q for q in QUOTE_RE.findall(raw) if _clean(q)]
    if quoted:
        term = _clean(quoted[-1])
        prefix = _clean(raw.replace(quoted[-1], " "))
        prefix = _clean(re.sub(r"[“\"'”]", " ", prefix))
        parts = prefix.split()
        ref = _normalize_subject_ref(parts[0]) if parts else ""
        return ref, term
    parts = raw.split(maxsplit=1)
    if len(parts) == 1:
        return _normalize_subject_ref(parts[0]), ""
    return _normalize_subject_ref(parts[0]), _clean(parts[1])




def _parse_ref_flags_filter(reference: str) -> tuple[str, bool, str]:
    """Parse /memory list operands into subject ref, --all flag, and optional term filter.

    Supports mobile IME dash variants such as `—all`/`–all`, and treats the
    first non-flag token as the subject reference while preserving the remaining
    text as a filter. This prevents `/memory list 3630529620 他是A` from being
    resolved as one giant user reference.
    """
    raw = _clean(reference)
    if not raw:
        return "", False, ""
    parts = raw.split()
    ref = ""
    include_all = False
    filters: list[str] = []
    for part in parts:
        token = _clean(part)
        if not token:
            continue
        if token in {"--all", "-all", "all", "全部", "全量"}:
            include_all = True
            continue
        if not ref:
            ref = _normalize_subject_ref(token)
        else:
            filters.append(token)
    return _normalize_subject_ref(ref), include_all, _clean(" ".join(filters))


def _resolve_user_id(backend: SocialCognitionStore, ref: str) -> str:
    ref = _normalize_subject_ref(ref)
    if not ref:
        return ""
    if re.fullmatch(r"\d{5,12}", ref):
        return ref
    try:
        return str(backend.resolve_user_reference(ref) or "")
    except Exception:
        return ""


def _row_haystack(row: dict[str, Any]) -> str:
    tags = " ".join(map(str, _json_loads(row.get("tags_json"), [])))
    return " ".join(
        _clean(str(row.get(k) or ""))
        for k in ("id", "memory_text", "raw_evidence", "source_type")
    ) + " " + tags


def _matches_term(row: dict[str, Any], term: str) -> bool:
    t = _clean(term)
    if not t:
        return False
    hay = _row_haystack(row)
    if t in hay:
        return True
    compact_t = re.sub(r"\s+", "", t).casefold()
    compact_hay = re.sub(r"\s+", "", hay).casefold()
    return bool(compact_t and compact_t in compact_hay)


def _restore_by_subject_term(backend: SocialCognitionStore, *, subject_ref: str, term: str, actor_user_id: str = "", only_last: bool = False) -> tuple[int, list[str]]:
    uid = _resolve_user_id(backend, subject_ref)
    if not uid:
        return 0, []
    with backend.connect() as conn:
        ensure_crud_tables(conn)
        rows = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM social_memories WHERE subject_user_id=? AND COALESCE(is_active, 1)=0 ORDER BY updated_at DESC, created_at DESC",
            (uid,),
        ).fetchall()]
        matches = [r for r in rows if _matches_term(r, term)] if term else rows[:1]
        if only_last and matches:
            last_time = str(matches[0].get("updated_at") or "")[:19]
            matches = [r for r in matches if str(r.get("updated_at") or "").startswith(last_time)] or matches[:1]
        if not matches:
            return 0, []
        now = utc_now()
        mids: list[str] = []
        for row in matches:
            mid = str(row.get("id") or "")
            if not mid:
                continue
            conn.execute("UPDATE social_memories SET is_active=1, updated_at=? WHERE id=?", (now, mid))
            new_row = dict(row)
            new_row["is_active"] = 1
            new_row["updated_at"] = now
            _revision(conn, memory_id=mid, old_row=row, new_row=new_row, actor_user_id=actor_user_id, reason="memory_command_restore")
            _audit(conn, action="restore", memory_id=mid, subject_user_id=uid, actor_user_id=actor_user_id, scope_id=str(row.get("scope_id") or ""), before=row, after=new_row, reason="memory_command_restore")
            mids.append(mid)
        return len(mids), mids


def format_status(*, store: SocialCognitionStore | None = None) -> str:
    backend = store or social_cognition_store
    stats = backend.stats()
    return _safe(
        "memory：已启用\n"
        f"群友数：{stats['users']}\n"
        f"认知记忆：{stats['memories']}\n"
        f"互动事件：{stats['interactions']}\n"
        "说明：内部以 platform user_id 为主键。"
    )


def format_add(rest: str, *, store: SocialCognitionStore | None = None, actor_user_id: str = "", scope_id: str = "", subject_hint: str = "") -> str:
    backend = store or social_cognition_store
    raw, tags = _extract_tags(rest, default="profile")
    ref, text = _split_ref_and_text(raw)
    hint = _normalize_subject_ref(subject_hint)
    if hint:
        # CommandArg.extract_plain_text() often drops @ segments.  In that case
        # `/memory add @A 他是A` arrives here as just `他是A`; the mention id is
        # the authoritative target and the remaining text is the memory body.
        if not ref or ref.startswith("@"):
            ref = hint
        elif not text and raw and not re.fullmatch(r"(?:@?\d{5,12}|@\S+)", raw):
            ref = hint
            text = raw
    if not ref or not text:
        return "用法：/memory add <账号ID或昵称> <记忆内容> [#profile|#alias|#skill|#preference]"
    crud = SocialMemoryCrud(backend)
    result = crud.create(subject_ref=ref, text=text, tags=tags, actor_user_id=actor_user_id, scope_id=scope_id)
    if not result.ok:
        return _safe("没记上：" + result.message)
    if hint:
        return _safe("好，记住啦。")
    return _safe("记住了 1 条。")


def format_edit(rest: str, *, store: SocialCognitionStore | None = None, actor_user_id: str = "") -> str:
    backend = store or social_cognition_store
    raw, tags = _extract_tags(rest, default="")
    mid_match = MEMORY_ID_RE.search(raw)
    if not mid_match:
        return "用法：/memory edit <memory_id> <新内容> [#profile|#alias|#skill|#preference]"
    mid = mid_match.group(1)
    text = _clean(raw.replace(mid, " "))
    if not text:
        return "没改：需要新的记忆内容。"
    crud = SocialMemoryCrud(backend)
    result = crud.update(memory_id=mid, new_text=text, tags=tags or None, actor_user_id=actor_user_id, reason="memory_command_edit")
    if not result.ok:
        return _safe("没改：" + result.message)
    return _safe(f"改好了 1 条：{result.memory_id}")


def format_list(reference: str, *, include_hidden: bool = False, store: SocialCognitionStore | None = None, subject_hint: str = "") -> str:
    backend = store or social_cognition_store
    ref, parsed_all, term_filter = _parse_ref_flags_filter(reference)
    if subject_hint and (not ref or ref.startswith("@")):
        ref = _normalize_subject_ref(subject_hint)
    include_hidden = bool(include_hidden or parsed_all)
    if not ref:
        return "用法：/memory list <账号ID或昵称> [可选关键词] [--all]"
    crud = SocialMemoryCrud(backend)
    result = crud.list(subject_ref=ref, include_hidden=include_hidden, limit=80)
    if not result.ok:
        return _safe(result.message)
    lines: list[str] = []
    for row in result.rows:
        mid = str(row.get("id") or "")
        active = int(row.get("is_active") if row.get("is_active") is not None else 1)
        gov = row.get("governance") or {}
        text = _clean(str(gov.get("display_text") or row.get("memory_text") or ""))
        raw_text = _clean(str(row.get("memory_text") or "") + " " + str(row.get("raw_evidence") or ""))
        if term_filter and term_filter not in text and term_filter not in raw_text:
            continue
        if not include_hidden and not active:
            continue
        status = "active" if active else "inactive"
        if not text:
            text = "（空）"
        lines.append(f"- {mid} [{status}] {text}")
    return _safe("\n".join(lines) if lines else "没有可展示的记忆。")


def format_inspect(reference: str, *, store: SocialCognitionStore | None = None, subject_hint: str = "") -> str:
    backend = store or social_cognition_store
    ref = _normalize_subject_ref(reference) or _normalize_subject_ref(subject_hint)
    if not ref:
        return "用法：/memory inspect <账号ID或昵称>"
    uid = _resolve_user_id(backend, ref)
    if not uid:
        return "还没找到这个群友的记录。"
    crud = SocialMemoryCrud(backend)
    result = crud.list(subject_ref=uid, include_hidden=False, limit=20)
    if not result.ok:
        return _safe(result.message)
    renderable: list[str] = []
    hidden = 0
    for row in result.rows:
        gov = row.get("governance") or {}
        text = _clean(str(gov.get("display_text") or row.get("memory_text") or ""))
        if gov and not gov.get("renderable", True):
            # CRUD-created profile facts that passed the typed write gate remain readable by operators.
            tags = set(map(str, _json_loads(row.get("tags_json"), [])))
            if str(row.get("source_type") or "").startswith("admin_crud") and tags & {"profile", "skill", "preference", "habit", "admin_confirmed"}:
                pass
            else:
                hidden += 1
                continue
        if text:
            renderable.append(f"- {text}")
    if renderable:
        return _safe("这个群友的印象：\n" + "\n".join(renderable[:8]))
    if hidden:
        return _safe(f"这个群友暂时没有可展示的稳定印象；另有 {hidden} 条被隐藏。")
    return "这个群友目前只有出现记录，还没有稳定印象。"


def format_events(reference: str = "", *, store: SocialCognitionStore | None = None, limit: int = 5) -> str:
    backend = store or social_cognition_store
    events = backend.recent_events(reference.strip() or None, limit=limit)
    if not events:
        return "还没有可展示的互动事件。"
    lines = ["最近互动事件："]
    for event in events:
        lines.append(f"- {event['message_text']}")
    return _safe("\n".join(lines))


def format_delete(rest: str, *, store: SocialCognitionStore | None = None, actor_user_id: str = "", subject_hint: str = "") -> str:
    backend = store or social_cognition_store
    raw = _clean(rest)
    if not raw:
        return "用法：/memory delete <memory_id> 或 /memory delete <账号ID或昵称> <关键词>"
    crud = SocialMemoryCrud(backend)
    mid = MEMORY_ID_RE.search(raw)
    if mid:
        result = crud.soft_delete(memory_id=mid.group(1), actor_user_id=actor_user_id, reason="memory_command_delete")
        return _safe(f"删掉了 {result.updated} 条。" if result.ok else "没删：没找到匹配的记忆。")
    ref, term = _split_ref_and_term(raw)
    if subject_hint and (not ref or ref.startswith("@")):
        ref = _normalize_subject_ref(subject_hint)
    if not term:
        if "--all" in raw and "--confirm" in raw:
            ref = _clean(raw.replace("--all", "").replace("--confirm", ""))
            result = crud.soft_delete(subject_ref=ref, terms=[], actor_user_id=actor_user_id, reason="memory_command_delete_all_confirmed")
            return _safe(f"删掉了 {result.updated} 条。" if result.ok else "没删：没找到匹配的记忆。")
        return "没删：需要 memory_id，或“群友 + 关键词”。整人清空要写 --all --confirm。"
    result = crud.soft_delete(subject_ref=ref, terms=[term], actor_user_id=actor_user_id, reason="memory_command_delete_term")
    return _safe(f"删掉了 {result.updated} 条。" if result.ok else "没删：没找到匹配的记忆。")


def format_restore(rest: str, *, store: SocialCognitionStore | None = None, actor_user_id: str = "", subject_hint: str = "") -> str:
    backend = store or social_cognition_store
    raw = _clean(rest)
    if not raw:
        return "用法：/memory restore <memory_id> 或 /memory restore <账号ID或昵称> <关键词>"
    crud = SocialMemoryCrud(backend)
    mid = MEMORY_ID_RE.search(raw)
    if mid:
        result = crud.restore(memory_id=mid.group(1), actor_user_id=actor_user_id, reason="memory_command_restore")
        return _safe(f"恢复了 {result.updated} 条。" if result.ok else "没恢复：没找到匹配的记忆。")
    ref, term = _split_ref_and_term(raw)
    if subject_hint and (not ref or ref.startswith("@")):
        ref = _normalize_subject_ref(subject_hint)
    only_last = term in {"--last", "last", "最近", "刚才"}
    if only_last:
        term = ""
    if not ref:
        return "没恢复：需要指定群友或 memory_id。"
    count, _ = _restore_by_subject_term(backend, subject_ref=ref, term=term, actor_user_id=actor_user_id, only_last=only_last)
    return _safe(f"恢复了 {count} 条。" if count else "没恢复：没找到匹配的记忆。")


def format_audit(reference: str = "", *, store: SocialCognitionStore | None = None) -> str:
    backend = store or social_cognition_store
    raw = _clean(reference)
    crud = SocialMemoryCrud(backend)
    mid = MEMORY_ID_RE.search(raw)
    result = crud.audit_log(memory_id=mid.group(1) if mid else "", subject_ref="" if mid else raw, limit=20)
    if not result.ok or not result.rows:
        return "没有可展示的操作记录。"
    lines = []
    for row in result.rows[:10]:
        action = str(row.get("action") or "")
        memory_id = str(row.get("memory_id") or "")
        created_at = str(row.get("created_at") or "")[:19]
        lines.append(f"- {created_at} {action} {memory_id}".strip())
    return _safe("\n".join(lines))


def format_forget(reference: str, *, store: SocialCognitionStore | None = None) -> str:
    return format_delete(reference, store=store)


def format_memory_add(
    subject_ref: str,
    text: str,
    *,
    tags: str = "profile",
    actor_user_id: str = "",
    store: SocialCognitionStore | None = None,
) -> str:
    tag_text = " ".join(f"#{tag}" for tag in str(tags or "profile").split())
    return format_add(f"{subject_ref} {text} {tag_text}", store=store, actor_user_id=actor_user_id)


def format_memory_list(
    subject_ref: str,
    *,
    include_hidden: bool = False,
    store: SocialCognitionStore | None = None,
) -> str:
    return format_list(subject_ref, include_hidden=include_hidden, store=store)


def format_memory_update(
    memory_id: str,
    text: str,
    *,
    tags: str | None = None,
    actor_user_id: str = "",
    store: SocialCognitionStore | None = None,
) -> str:
    tag_text = " ".join(f"#{tag}" for tag in str(tags or "").split())
    return format_edit(f"{memory_id} {text} {tag_text}", store=store, actor_user_id=actor_user_id)


def format_memory_delete(
    subject_or_memory_id: str,
    term: str = "",
    *,
    actor_user_id: str = "",
    store: SocialCognitionStore | None = None,
) -> str:
    return format_delete(f"{subject_or_memory_id} {term}".strip(), store=store, actor_user_id=actor_user_id)


def format_memory_restore(
    subject_or_memory_id: str,
    *,
    actor_user_id: str = "",
    store: SocialCognitionStore | None = None,
) -> str:
    return format_restore(subject_or_memory_id, store=store, actor_user_id=actor_user_id)


def format_memory_audit(reference: str = "", *, store: SocialCognitionStore | None = None) -> str:
    return format_audit(reference, store=store)
