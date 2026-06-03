from __future__ import annotations

"""Natural-language control plane for social memory CRUD.

This module deliberately separates three concerns:
1. Parse a natural admin request into a typed action plan.
2. Execute that action through SocialMemoryCrud only; never mutate raw rows ad hoc.
3. Render a short Bot-style operational reply without database/admin/audit wording.

The parser is deterministic and schema-based so it can be safely replaced or
augmented later by an LLM tool-calling layer that emits the same
NaturalMemoryAction schema. Destructive actions remain permission-gated in the
NoneBot plugin and auditable in SocialMemoryCrud.
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .memory_crud import SocialMemoryCrud, CrudResult, extract_label_value, normalize_tags

BOT_NAME_RE = re.compile(r"(@?Bot|@?机器人)", re.I)
CQ_AT_RE = re.compile(r"\[CQ:at,qq=(\d{5,12})\]")
QQ_RE = re.compile(r"(?<!\d)(\d{5,12})(?!\d)")
MEMORY_WORD_RE = re.compile(r"(记忆|印象|记住|记一下|记录|memory)", re.I)
WRITE_WORD_RE = re.compile(r"(删除|删掉|删去|清除|忘掉|移除|新增|添加|加一条|记住|记一下|修改|更改|改成|改为|更正|更新|恢复)")
DELETE_WORD_RE = re.compile(r"(删除|删掉|删去|清除|忘掉|移除)")
ADD_WORD_RE = re.compile(r"(新增|添加|加一条|记住|记一下|记录)")
UPDATE_WORD_RE = re.compile(r"(修改|更改|改成|改为|更正|更新)")
RESTORE_WORD_RE = re.compile(r"(恢复|还原)")
MEMORY_ID_RE = re.compile(r"\b(smem_[A-Za-z0-9_\-]+)\b")
QUOTE_RE = re.compile(r"[“\"']([^”\"']{1,220})[”\"']")
TAG_RE = re.compile(r"#([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})")

FORBIDDEN_REPLY_RE = re.compile(r"(我这边|管理员|数据库|审计|audit|source|trust|高可信|低可信|系统记录|后台)", re.I)


@dataclass(frozen=True)
class NaturalMemoryAction:
    op: str
    target_ref: str = ""
    memory_id: str = ""
    term: str = ""
    new_text: str = ""
    tags: str = "profile"
    confidence: float = 0.0
    reason: str = ""

    @property
    def executable(self) -> bool:
        if self.op in {"delete", "update", "create", "restore"}:
            return bool(self.memory_id or self.target_ref)
        return False


@dataclass(frozen=True)
class NaturalMemoryExecution:
    ok: bool
    reply: str
    action: NaturalMemoryAction
    updated: int = 0
    memory_id: str = ""


def normalize_natural_text(text: str) -> str:
    raw = str(text or "")
    raw = CQ_AT_RE.sub(" ", raw)
    raw = BOT_NAME_RE.sub(" ", raw)
    raw = TAG_RE.sub(lambda m: " #" + m.group(1) + " ", raw)
    raw = raw.replace("＃", "#")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n，,。.;；：:")


def _quoted(text: str) -> list[str]:
    return [_clean(x) for x in QUOTE_RE.findall(text or "") if _clean(x)]


def _strip_tags(text: str) -> tuple[str, str]:
    tags = TAG_RE.findall(text or "")
    clean = TAG_RE.sub("", text or "").strip()
    return clean, " ".join(tags) if tags else ""


def infer_tags(text: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    raw = _clean(text)
    if re.search(r"(叫作|叫做|叫|称作|称为|昵称|外号|被叫|被称|alias|nickname)", raw, re.I):
        return "alias"
    if re.search(r"(会|擅长|技能|skill)", raw, re.I):
        return "skill"
    if re.search(r"(喜欢|偏好|爱好|preference)", raw, re.I):
        return "preference"
    return "profile"


def _target_from_text(text: str, mentioned_user_ids: Iterable[str] | None) -> str:
    mentions = [str(x).strip() for x in (mentioned_user_ids or []) if str(x).strip()]
    if mentions:
        return mentions[0]
    m = QQ_RE.search(text or "")
    return m.group(1) if m else ""


def _remove_target_noise(text: str, target_ref: str) -> str:
    out = str(text or "")
    if target_ref:
        out = out.replace(target_ref, " ")
    out = re.sub(r"@[\w\u4e00-\u9fff·・ー\-]{1,32}", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _extract_add_payload(text: str) -> str:
    raw = _clean(text)
    qs = _quoted(raw)
    if qs:
        return qs[-1]
    # Common forms: 给@A加一条记忆：xxx / 记住@A xxx / @A 叫 ph
    m = re.search(r"(?:记忆|印象|记录)\s*[：:]\s*(.+)$", raw, re.S)
    if m:
        return _clean(m.group(1))
    m = re.search(r"(?:新增|添加|加一条|记住|记一下|记录)\s*(?:一下|一条)?\s*(?:[^，。:：]{0,40})[：:]\s*(.+)$", raw, re.S)
    if m:
        return _clean(m.group(1))
    m = re.search(r"(?:叫作|叫做|叫|称作|称为|昵称是|外号是)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", raw)
    if m:
        return m.group(1)
    m = re.search(r"(?:新增|添加|加一条|记住|记一下|记录)\s*(.+)$", raw, re.S)
    if m:
        candidate = _clean(m.group(1))
        candidate = re.sub(r"^(?:给|把|将)?\s*(?:这个|该)?群友的?", "", candidate)
        return _clean(candidate)
    return ""


def _extract_delete_term(text: str, target_ref: str) -> str:
    raw = _clean(text)
    qs = _quoted(raw)
    if qs:
        return qs[0]
    mid = MEMORY_ID_RE.search(raw)
    if mid:
        return ""
    patterns = (
        r"(?:关于|包含|带有|里面有|含有)\s*(.+?)\s*的?(?:这条|那条|某条)?(?:记忆|印象|记录)",
        r"(?:是|叫作|叫做|叫|称作|称为)\s*(.+?)\s*的?(?:这条|那条|某条)?(?:记忆|印象|记录)",
        r"(?:删除|删掉|删去|清除|忘掉|移除).{0,60}?\s+(.+?)\s*的?(?:记忆|印象|记录)",
    )
    for pat in patterns:
        m = re.search(pat, raw, re.S)
        if m:
            val = _clean(m.group(1))
            val = _clean(re.sub(r"^(?:给|把|将|这个|该|群友|他|她|它|ta|TA|的|某条|那条|这条)+", "", val))
            if val and not DELETE_WORD_RE.fullmatch(val):
                return val
    no_target = _remove_target_noise(raw, target_ref)
    no_target = DELETE_WORD_RE.sub(" ", no_target)
    no_target = re.sub(r"(把|将|给|的|某条|这条|那条|记忆|印象|记录|删掉|删去|删除|清除|忘掉|移除)", " ", no_target)
    no_target = _clean(no_target)
    return no_target if 1 <= len(no_target) <= 80 else ""


def _extract_update_parts(text: str, target_ref: str) -> tuple[str, str]:
    raw = _clean(text)
    qs = _quoted(raw)
    if len(qs) >= 2:
        return qs[0], qs[1]
    # 把@A关于Python的记忆改成喜欢 Rust
    m = re.search(r"(?:关于|包含|带有|里面有|含有)\s*(.+?)\s*(?:的)?(?:记忆|印象|记录).{0,20}?(?:改成|改为|更改为|修改为|更新为|更正为)\s*(.+)$", raw, re.S)
    if m:
        return _clean(m.group(1)), _clean(m.group(2))
    m = re.search(r"(?:把|将)?(.+?)(?:这条|那条|某条)?(?:记忆|印象|记录)?.{0,20}?(?:改成|改为|更改为|修改为|更新为|更正为)\s*(.+)$", _remove_target_noise(raw, target_ref), re.S)
    if m:
        old = _clean(re.sub(r"^(?:的|关于)", "", m.group(1)))
        new = _clean(m.group(2))
        return old, new
    return "", ""


def parse_natural_memory_request(text: str, *, mentioned_user_ids: Iterable[str] | None = None) -> NaturalMemoryAction | None:
    raw = normalize_natural_text(text)
    if not raw:
        return None
    has_memory_word = bool(MEMORY_WORD_RE.search(raw))
    has_write_word = bool(WRITE_WORD_RE.search(raw))
    if not (has_memory_word and has_write_word):
        # Allow concise alias creation like “记住@A叫ph”; still must include a write word.
        return None
    clean_no_tags, explicit_tags = _strip_tags(raw)
    target_ref = _target_from_text(clean_no_tags, mentioned_user_ids)
    mid_match = MEMORY_ID_RE.search(clean_no_tags)
    memory_id = mid_match.group(1) if mid_match else ""

    if DELETE_WORD_RE.search(clean_no_tags):
        term = _extract_delete_term(clean_no_tags, target_ref)
        if memory_id:
            return NaturalMemoryAction("delete", memory_id=memory_id, term="", confidence=0.95, reason="memory_id_delete")
        if not target_ref:
            return NaturalMemoryAction("delete", term=term, confidence=0.35, reason="missing_target")
        if not term:
            return NaturalMemoryAction("delete", target_ref=target_ref, confidence=0.55, reason="missing_delete_term")
        return NaturalMemoryAction("delete", target_ref=target_ref, term=term, confidence=0.92, reason="target_term_delete")

    if UPDATE_WORD_RE.search(clean_no_tags):
        old, new = _extract_update_parts(clean_no_tags, target_ref)
        tags = infer_tags(new or clean_no_tags, explicit_tags)
        if memory_id and new:
            return NaturalMemoryAction("update", target_ref=target_ref, memory_id=memory_id, new_text=new, tags=tags, confidence=0.95, reason="memory_id_update")
        if target_ref and old and new:
            return NaturalMemoryAction("update", target_ref=target_ref, term=old, new_text=new, tags=tags, confidence=0.88, reason="target_term_update")
        return NaturalMemoryAction("update", target_ref=target_ref, term=old, new_text=new, tags=tags, confidence=0.45, reason="incomplete_update")

    if RESTORE_WORD_RE.search(clean_no_tags):
        if memory_id:
            return NaturalMemoryAction("restore", memory_id=memory_id, confidence=0.94, reason="memory_id_restore")
        return NaturalMemoryAction("restore", target_ref=target_ref, confidence=0.4, reason="missing_memory_id")

    if ADD_WORD_RE.search(clean_no_tags):
        payload = _extract_add_payload(clean_no_tags)
        tags = infer_tags(clean_no_tags + " " + (payload or ""), explicit_tags)
        # For “记住@A叫ph”, store only the label value under alias policy.
        if tags == "alias":
            label = extract_label_value(payload) or payload
            payload = label
        if target_ref and payload:
            return NaturalMemoryAction("create", target_ref=target_ref, new_text=payload, tags=tags, confidence=0.88, reason="target_add")
        return NaturalMemoryAction("create", target_ref=target_ref, new_text=payload, tags=tags, confidence=0.45, reason="incomplete_create")

    return None


def _safe_reply(text: str) -> str:
    # Preserve formatter punctuation; _clean() strips
    # punctuation for parser matching and should not be used on final replies.
    out = str(text or "")
    out = FORBIDDEN_REPLY_RE.sub("", out)
    out = re.sub(r"[ \t\r\n]+", " ", out).strip(" \t\r\n")
    return out or "操作完成。"


def _crud_reply(result: CrudResult, *, ok_prefix: str, fail_prefix: str = "没改动") -> str:
    if result.ok:
        if ok_prefix.startswith("记住"):
            return _safe_reply("好，记住啦。")
        if ok_prefix.startswith("删"):
            return _safe_reply("删掉了 1 条。" if result.updated else "没删到匹配的记忆。")
        if ok_prefix.startswith("改"):
            return _safe_reply("改好了 1 条。" if result.updated else "没改到匹配的记忆。")
        if ok_prefix.startswith("恢复"):
            return _safe_reply("恢复了 1 条。" if result.updated else "没恢复到匹配的记忆。")
        return _safe_reply("处理完成。")
    msg = result.message
    if "没有找到" in msg or "没对上" in msg:
        return _safe_reply(f"{fail_prefix}：没找到匹配的记忆。")
    if "不符合" in msg or "未新增" in msg:
        return _safe_reply("这条不像稳定的群友记忆，没有写入。")
    return _safe_reply(f"{fail_prefix}：{msg}")


def _update_by_target_term(crud: SocialMemoryCrud, *, target_ref: str, term: str, new_text: str, tags: str, actor_user_id: str) -> NaturalMemoryExecution:
    listed = crud.list(subject_ref=target_ref, include_hidden=False, limit=80)
    action = NaturalMemoryAction("update", target_ref=target_ref, term=term, new_text=new_text, tags=tags)
    if not listed.ok:
        return NaturalMemoryExecution(False, _safe_reply("没改动：没找到这个群友。"), action)
    matches = []
    for row in listed.rows:
        hay = f"{row.get('memory_text','')} {row.get('raw_evidence','')}"
        if term and term in hay:
            matches.append(str(row.get("id") or ""))
    if not matches:
        return NaturalMemoryExecution(False, _safe_reply("没改动：没找到匹配的记忆。"), action)
    updated = 0
    last_mid = ""
    for mid in matches:
        if not mid:
            continue
        result = crud.update(memory_id=mid, new_text=new_text, tags=tags, actor_user_id=actor_user_id, reason="admin_natural_language_update")
        if result.ok:
            updated += 1
            last_mid = mid
    if updated:
        return NaturalMemoryExecution(True, _safe_reply(f"改好了 {updated} 条。"), action, updated=updated, memory_id=last_mid)
    return NaturalMemoryExecution(False, _safe_reply("没改动：匹配到了，但修改没有成功。"), action)


def execute_natural_memory_action(store: Any, action: NaturalMemoryAction, *, actor_user_id: str = "", scope_id: str = "") -> NaturalMemoryExecution:
    crud = SocialMemoryCrud(store)
    if action.op == "create":
        if not action.target_ref or not action.new_text:
            return NaturalMemoryExecution(False, _safe_reply("没写入：需要指定群友和记忆内容。"), action)
        result = crud.create(subject_ref=action.target_ref, text=action.new_text, tags=action.tags, actor_user_id=actor_user_id, scope_id=scope_id, source_type="admin_natural_language_crud")
        return NaturalMemoryExecution(result.ok, _crud_reply(result, ok_prefix="记住了", fail_prefix="没写入"), action, updated=result.updated, memory_id=result.memory_id)
    if action.op == "delete":
        if action.memory_id:
            result = crud.soft_delete(memory_id=action.memory_id, actor_user_id=actor_user_id, reason="admin_natural_language_delete")
        elif action.target_ref and action.term:
            result = crud.soft_delete(subject_ref=action.target_ref, terms=[action.term], actor_user_id=actor_user_id, reason="admin_natural_language_delete")
        else:
            return NaturalMemoryExecution(False, _safe_reply("没删：需要指定群友和要删的记忆关键词。"), action)
        return NaturalMemoryExecution(result.ok, _crud_reply(result, ok_prefix="删掉了", fail_prefix="没删"), action, updated=result.updated, memory_id=result.memory_id)
    if action.op == "update":
        if action.memory_id and action.new_text:
            result = crud.update(memory_id=action.memory_id, new_text=action.new_text, tags=action.tags, actor_user_id=actor_user_id, reason="admin_natural_language_update")
            return NaturalMemoryExecution(result.ok, _crud_reply(result, ok_prefix="改好了", fail_prefix="没改动"), action, updated=result.updated, memory_id=result.memory_id)
        if action.target_ref and action.term and action.new_text:
            return _update_by_target_term(crud, target_ref=action.target_ref, term=action.term, new_text=action.new_text, tags=action.tags, actor_user_id=actor_user_id)
        return NaturalMemoryExecution(False, _safe_reply("没改动：需要指定原记忆和新内容。"), action)
    if action.op == "restore":
        if not action.memory_id:
            return NaturalMemoryExecution(False, _safe_reply("没恢复：需要 memory_id。"), action)
        result = crud.restore(memory_id=action.memory_id, actor_user_id=actor_user_id, reason="admin_natural_language_restore")
        return NaturalMemoryExecution(result.ok, _crud_reply(result, ok_prefix="恢复了", fail_prefix="没恢复"), action, updated=result.updated, memory_id=result.memory_id)
    return NaturalMemoryExecution(False, _safe_reply("没识别到可执行的记忆操作。"), action)




def parse_natural_memory_action(text: str, *, mentioned_user_ids: Iterable[str] | None = None) -> NaturalMemoryAction | None:
    """Stable public API used by tests/plugins/scripts.

    Internally v27+ calls the parser `parse_natural_memory_request`, but the
    external action API remains `parse_natural_memory_action` so command and
    live plugins do not drift across patch versions.
    """
    return parse_natural_memory_request(text, mentioned_user_ids=mentioned_user_ids)

def admin_id_set() -> set[str]:
    raw = os.getenv("CHATBOT_MEMORY_ADMIN_IDS", "")
    return {x.strip() for x in re.split(r"[,，\s]+", raw) if x.strip()}


def is_bound_memory_admin(user_id: str, *, require_admin_result: bool = False) -> bool:
    uid = str(user_id or "").strip()
    return bool(require_admin_result or (uid and uid in admin_id_set()))
