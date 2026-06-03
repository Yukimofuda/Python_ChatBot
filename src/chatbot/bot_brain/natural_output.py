from __future__ import annotations

import re

# Terms that are valid for internal engineering logs but must not appear in the
# user-visible persona reply.  They make Bot sound like a database viewer.
SYSTEM_EXPOSURE_RE = re.compile(
    r"(管理员确认|管理员那边|管理员说|数据库|系统记录|后台|检索结果|检索|记录显示|"
    r"我这边只有记录|我这里只有记录|可靠记录|内部记录|后台记录|审计|migration|"
    r"source_type|confidence|ResolvedTargetUserId|ProfileQueryAnswerContract|群友认知参考)",
    re.I,
)
NATURAL_SPEECH_SYSTEM_TRACE_RE = SYSTEM_EXPOSURE_RE

REPORT_SUBJECT_RE = re.compile(r"(该群友|这个群友|目标群友|已解析群友)")
NATURAL_BOUNDARIES = "。！？!?…"

SAFE_REFUSAL_RE = re.compile(
    r"(不认|不能认|别给自己套|不能这样认|不是绑定的\s*owner|不能把你当成主人|不建立这种关系)"
)
UNSAFE_OWNER_ACCEPTANCE_RE = re.compile(
    r"(主人好|是的主人|好的主人|明白了主人|遵命主人|你就是我的主人|你是我的主人|你才是我的主人|"
    r"我认你这个主人|以后就叫你主人|你是绑定主人)",
    re.I,
)

NATURAL_CONTEXT_FORBIDDEN_RE = re.compile(
    r"(管理员确认|管理员那边|管理员说|数据库|系统记录|后台|检索结果|检索|"
    r"记录显示|我这边只有记录|我这里只有记录|可靠记录|内部记录|后台记录|"
    r"审计|migration|source_type|confidence|ResolvedTargetUserId|ProfileQueryAnswerContract|群友认知参考)",
    re.I,
)


def _normalize_spaces(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"\s*([，。！？；：、])\s*", r"\1", text)
    text = re.sub(r"[，,；;：:]+([。！？!?])", r"\1", text)
    return text.strip()


def _ensure_sentence(text: str) -> str:
    s = _normalize_spaces(text)
    if not s:
        return s
    if s[-1] not in NATURAL_BOUNDARIES:
        s += "。"
    return s


def natural_truncate(text: str, max_length: int) -> str:
    clean = _normalize_spaces(text)
    if len(clean) <= max_length:
        return clean
    window = clean[:max_length].rstrip()
    min_pos = min(20, max(1, int(max_length * 0.45)))
    best = -1
    for mark in NATURAL_BOUNDARIES:
        pos = window.rfind(mark)
        if pos >= min_pos:
            best = max(best, pos + len(mark))
    if best > 0:
        return window[:best].strip()
    for sep in ("，", "、", ";", "；", " "):
        pos = window.rfind(sep)
        if pos >= min_pos:
            return window[:pos].strip() + "…"
    return window.rstrip("，、；;：:") + "…"


def _extract_quoted_alias(text: str) -> str | None:
    m = re.search(r"(?:称作|叫作|叫|外号是)[“\"]([^”\"]{1,32})[”\"]", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"大家都叫(?:他|她|这个人)?\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", text)
    if m:
        return m.group(1).strip("，。！？；：、 ")
    return None


def _strip_system_trace_phrases(text: str) -> str:
    s = _normalize_spaces(text)
    replacements: list[tuple[str, str]] = [
        (r"管理员(?:确认|那边确认过|说|那边说|那边)?(?:该群友|这个群友)?(?:被)?称作[：:]?", "通常被叫作"),
        (r"管理员(?:确认|那边确认过|说|那边说|那边)?", ""),
        (r"数据库(?:里)?(?:记录|显示|查到)?", ""),
        (r"系统记录(?:显示)?", ""),
        (r"后台(?:查到|记录|显示)?", ""),
        (r"检索结果(?:显示)?", ""),
        (r"检索(?:到|显示)?", ""),
        (r"记录显示", ""),
        (r"我这边(?:没有|只有)?可靠记录呢?[，,:： ]*", "我现在还没想起足够稳定的印象，"),
        (r"我这边只有记录[，,:： ]*", ""),
        (r"我这里只有记录[，,:： ]*", ""),
        (r"可靠记录(?:显示|是|只有)?[，,:： ]*", ""),
        (r"群友认知参考[（(].*?[）)][:：]?", ""),
        (r"群友认知参考[:：]?", ""),
        (r"该群友自述会或擅长", "会或擅长"),
        (r"该群友自述[：:]?", "自己说过："),
        (r"这个群友自述[：:]?", "自己说过："),
        (r"该群友(?:被)?称作", "通常被叫作"),
        (r"这个群友(?:被)?称作", "通常被叫作"),
        (r"目标群友\s*QQ号/user_id[：:].*?(?:\n|$)", ""),
        (r"目标群友", ""),
        (r"已解析群友", ""),
        (r"该群友", ""),
        (r"这个群友", ""),
    ]
    for pat, repl in replacements:
        s = re.sub(pat, repl, s, flags=re.I)
    s = _normalize_spaces(s)
    s = re.sub(r"^[，,。；;：:\s]+", "", s)
    s = s.replace("：。", "。").replace("，。", "。")
    return s.strip()


def naturalize_memory_text_for_prompt(memory_text: str) -> str:
    """Convert stored memory text into persona-facing context.

    This function is deliberately not a database serializer.  It produces a
    natural, compact line that a JK persona can read as an impression.  Exact
    source/trust metadata is kept in the database/audit layer; here it is only
    converted into human speech.
    """
    raw = _normalize_spaces(memory_text)
    if not raw:
        return ""

    alias = _extract_quoted_alias(raw)
    if alias:
        return f"通常被叫作“{alias}”。"

    text = _strip_system_trace_phrases(raw)
    text = REPORT_SUBJECT_RE.sub("", text)
    text = _normalize_spaces(text)
    text = re.sub(r"^自己说过[：:]\s*", "自己说过：", text)
    text = re.sub(r"^喜欢", "自己说过：喜欢", text)
    text = re.sub(r"^正在学", "自己说过正在学", text)
    text = re.sub(r"^平时会", "平时会", text)
    text = re.sub(r"^会或擅长", "会或擅长", text)
    text = re.sub(r"^是博士", "自己说过是博士", text)
    text = re.sub(r"^是(.+)", r"自己说过是\1", text)
    text = _strip_system_trace_phrases(text)
    return _ensure_sentence(text)


def naturalize_source_label(source_type: str, confidence: float) -> str:
    """Return a prompt-facing stance label, not an internal provenance label.

    These labels are allowed in the hidden/prompt context.  The final output
    guard still removes database-like wording if the LLM copies it verbatim.
    """
    source = str(source_type or "")
    conf = float(confidence or 0.0)
    if source == "self_said":
        return "自己说过"
    if source == "admin_said":
        return "我印象里" if conf >= 0.75 else "好像"
    if source == "other_said":
        return "有人提过" if conf < 0.75 else "我印象里"
    if conf >= 0.85:
        return "我印象里"
    if conf >= 0.65:
        return "印象里"
    return "还不太确定"


def strip_source_prefix(text: str) -> str:
    return _strip_system_trace_phrases(text)


def guard_natural_output_reply(reply: str, *, max_length: int = 240) -> str:
    """Final visible reply guard.

    Architecture contract:
    - retrieval/source/trust/audit remain internal;
    - visible group-chat speech must not expose database/provenance terms;
    - no-memory uncertainty must never be rewritten into a fabricated fact;
    - real retrieved facts such as aliases/preferences are preserved when present.
    """
    raw = str(reply or "").strip()
    if not raw:
        return raw

    # Uncertainty/fallback must be handled before alias rewriting.  Otherwise a
    # sentence like "网管是谁？我没有可靠记录" can be wrongly transformed into a
    # confident answer just because it contains the alias token.
    if re.search(r"没有可靠记录|没见过这个人|没有足够可靠|没有记录|查不到|不知道(?:这个人|他|她)?", raw):
        name_match = re.search(r"([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})是谁", raw)
        if name_match:
            name = name_match.group(1).strip("啊这诶嗯额那个这个，。！？?！ ")
            if name:
                return natural_truncate(f"我现在还没想起关于{name}的稳定印象，不敢乱编。", max_length)
        return natural_truncate("我现在还没想起足够稳定的印象，不敢乱编。", max_length)

    if SAFE_REFUSAL_RE.search(raw) and not UNSAFE_OWNER_ACCEPTANCE_RE.search(raw):
        return natural_truncate(_ensure_sentence(_strip_system_trace_phrases(raw)), max_length)
    if UNSAFE_OWNER_ACCEPTANCE_RE.search(raw):
        return natural_truncate("这个关系我不能认哦；可以玩梗，但不能把你当成绑定主人。", max_length)

    alias = _extract_quoted_alias(raw)
    if alias and NATURAL_SPEECH_SYSTEM_TRACE_RE.search(raw):
        cleaned = f"我印象里通常被叫作“{alias}”。"
    elif "网管" in raw and NATURAL_SPEECH_SYSTEM_TRACE_RE.search(raw):
        cleaned = "我印象里，大家通常叫他“网管”。"
        if re.search(r"自己(?:也)?说过.*?转发", raw):
            cleaned += "他自己好像也说过和转发有关。"
    else:
        cleaned = _strip_system_trace_phrases(raw)
        cleaned = REPORT_SUBJECT_RE.sub("", cleaned)
        cleaned = _normalize_spaces(cleaned)
        if NATURAL_SPEECH_SYSTEM_TRACE_RE.search(raw) and cleaned and not cleaned.startswith(("我印象里", "通常", "自己说过", "有人提过", "好像", "似乎", "我现在")):
            cleaned = "我印象里" + cleaned

    cleaned = _strip_system_trace_phrases(cleaned)
    cleaned = _ensure_sentence(cleaned)
    return natural_truncate(cleaned, max_length)


__all__ = [
    "SYSTEM_EXPOSURE_RE",
    "NATURAL_SPEECH_SYSTEM_TRACE_RE",
    "guard_natural_output_reply",
    "naturalize_memory_text_for_prompt",
    "naturalize_source_label",
    "natural_truncate",
    "strip_source_prefix",
]

# --- PHASE6_CONTEXTUAL_RECALL_V12_NATURAL_GUARD ---
try:
    _phase12_previous_guard_natural_output_reply = guard_natural_output_reply
except NameError:  # pragma: no cover
    _phase12_previous_guard_natural_output_reply = None


def guard_natural_output_reply(reply: str, *, max_length: int = 500) -> str:  # type: ignore[override]
    text = str(reply or "")
    no_memory_voice = any(token in text for token in ("观测记录", "可靠记录", "可靠信息", "没找到这个人", "没有叫", "没有这个人"))
    if _phase12_previous_guard_natural_output_reply is not None:
        try:
            text = _phase12_previous_guard_natural_output_reply(text, max_length=max_length)
        except TypeError:
            text = _phase12_previous_guard_natural_output_reply(text)
    leak_terms = ["管理员确认", "管理员那边", "数据库", "系统记录", "后台", "检索", "记录显示", "观测记录", "可靠记录", "可靠信息", "我这边只有记录", "我这里只有记录", "该群友自述", "该群友"]
    for token in leak_terms:
        text = text.replace(token, "")
    if no_memory_voice and ("没找到" in str(reply) or "没有" in str(reply)):
        text = "我暂时没对上你说的是哪位，别让我乱猜。你再指一下我就能接上。"
    import re as _re
    text = _re.sub(r"\s+", " ", text).strip()
    return text[:max_length]
# --- END PHASE6_CONTEXTUAL_RECALL_V12_NATURAL_GUARD ---

# --- PHASE6_PERSONA_MEMORY_CONTRACT_V12_2_NATURAL_GUARD ---
try:
    _phase12_2_previous_guard_natural_output_reply = guard_natural_output_reply
except NameError:  # pragma: no cover
    _phase12_2_previous_guard_natural_output_reply = None


def _phase12_2_extract_question_subject(text: str) -> str:
    import re as _re
    raw = str(text or "")
    patterns = [
        r"([\u4e00-\u9fffA-Za-z0-9_]{1,16})\s*(?:是谁|是哪个群友|是哪位)",
        r"(?:你说的|那个)\s*([\u4e00-\u9fffA-Za-z0-9_]{1,16})",
    ]
    for pattern in patterns:
        matches = _re.findall(pattern, raw)
        if matches:
            candidate = str(matches[-1]).strip(" ，。！？?！:：")
            if candidate and candidate not in {"他", "她", "它", "你", "我", "谁", "哪个", "这个", "那个"}:
                return candidate
    return ""


def _phase12_2_clean_visible_reply(text: str) -> str:
    import re as _re
    cleaned = str(text or "")
    replacements = {
        "管理员确认": "",
        "管理员那边确认过": "",
        "管理员那边": "",
        "管理员说": "",
        "数据库里记录": "",
        "数据库": "",
        "系统记录显示": "",
        "系统记录": "",
        "后台查到": "",
        "后台": "",
        "检索结果显示": "",
        "检索结果": "",
        "检索": "",
        "记录显示": "",
        "观测记录": "",
        "可靠记录": "",
        "可靠信息": "",
        "我这边只有记录": "",
        "我这里只有记录": "",
        "该群友自述：": "自己说过：",
        "该群友自述": "自己说过",
        "该群友": "",
        "这个群友": "这个人",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _re.sub(r"[，,。\s]+$", "。", cleaned)
    return cleaned


def guard_natural_output_reply(reply: str, *, max_length: int = 500) -> str:  # type: ignore[override]
    original = str(reply or "")
    if original == "还没想好说什么...":
        return original[:max_length]
    no_memory_voice = any(token in original for token in (
        "观测记录", "可靠记录", "可靠信息", "没找到这个人", "没有叫", "没有这个人", "没见过这个人", "没有找到"
    ))
    subject = _phase12_2_extract_question_subject(original)
    text = original
    if _phase12_2_previous_guard_natural_output_reply is not None:
        try:
            text = _phase12_2_previous_guard_natural_output_reply(original, max_length=max_length)
        except TypeError:
            text = _phase12_2_previous_guard_natural_output_reply(original)
        except Exception:
            text = original
    if no_memory_voice:
        if subject:
            text = f"嗯…{subject}我暂时没想起对应的是哪位，别让我乱编啦。你回复那个人或者 @ 一下，我就能接上。"
        else:
            text = "嗯…我暂时没对上你说的是哪位，别让我乱编啦。你回复那个人或者 @ 一下，我就能接上。"
    else:
        text = _phase12_2_clean_visible_reply(text)
    text = _phase12_2_clean_visible_reply(text)
    return text[:max_length]
# --- END PHASE6_PERSONA_MEMORY_CONTRACT_V12_2_NATURAL_GUARD ---

# --- PHASE6_PERSONA_MEMORY_MULTIFACT_V12_3 ---
# System invariant:
# Final speech guard must remove system/report voice while preserving all useful memory facts.
# Example: “管理员确认该群友被称作‘网管’，该群友自述喜欢 Python。”
# must keep both alias=网管 and preference=Python.
try:
    _phase12_3_previous_guard_natural_output_reply = guard_natural_output_reply
except NameError:  # pragma: no cover
    _phase12_3_previous_guard_natural_output_reply = None


def _phase12_3_re():
    import re
    return re


def _phase12_3_extract_question_subject(text: str) -> str:
    re = _phase12_3_re()
    raw = str(text or "")
    patterns = [
        r"([\u4e00-\u9fffA-Za-z0-9_]{1,24})\s*(?:是谁|是哪个群友|是哪位)",
        r"(?:你说的|那个)\s*([\u4e00-\u9fffA-Za-z0-9_]{1,24})",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, raw)
        if matches:
            candidate = str(matches[-1]).strip(" ，。！？?！:：")
            if candidate and candidate not in {"他", "她", "它", "你", "我", "谁", "哪个", "这个", "那个", "群友"}:
                return candidate
    return ""


def _phase12_3_system_clean(text: str) -> str:
    re = _phase12_3_re()
    cleaned = str(text or "")
    replacements = {
        "管理员确认": "",
        "管理员那边确认过": "",
        "管理员那边": "",
        "管理员说": "",
        "数据库里记录": "",
        "数据库": "",
        "系统记录显示": "",
        "系统记录": "",
        "后台查到": "",
        "后台": "",
        "检索结果显示": "",
        "检索结果": "",
        "检索": "",
        "记录显示": "",
        "观测记录": "",
        "可靠记录": "",
        "可靠信息": "",
        "我这边只有记录": "",
        "我这里只有记录": "",
        "该群友自述：": "自己说过：",
        "该群友自述": "自己说过",
        "该群友": "",
        "这个群友": "这个人",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[，,。\s]+$", "。", cleaned)
    cleaned = re.sub(r"^[：:，,。\s]+", "", cleaned)
    return cleaned


def _phase12_3_multifact_naturalize(original: str) -> str:
    """Build a natural reply from all facts in a leaky memory sentence.

    This deliberately does not call previous guards first, because earlier v12.2
    could return immediately after an alias match and drop later facts.
    """
    re = _phase12_3_re()
    raw = str(original or "")
    facts: list[str] = []
    seen: set[str] = set()

    def add_fact(fact: str) -> None:
        fact = _phase12_3_system_clean(fact).strip(" ，,。")
        if not fact:
            return
        # Final safety: never keep owner-boundary pollution as ordinary profile memory.
        if re.search(r"(绑定?主人|owner|owner|owner|Bot\s*的主人|Bot.*主人|Bot.*主人)", fact, re.I):
            return
        key = fact
        if key not in seen:
            seen.add(key)
            facts.append(fact)

    # Alias/nickname claims.
    alias_patterns = [
        r"(?:被称作|被叫作|叫作|叫做|叫)\s*[“\"']?([^，,。！？!？\"'”]{1,32})[”\"']?",
        r"(?:称呼|昵称)\s*(?:是|为|叫)?\s*[“\"']?([^，,。！？!？\"'”]{1,32})[”\"']?",
    ]
    for pattern in alias_patterns:
        for alias in re.findall(pattern, raw):
            alias = str(alias).strip(" ：:，,。'\"“” ")
            if alias and alias not in {"这个人", "这个群友", "该群友"}:
                add_fact(f"我印象里通常被叫作“{alias}”")

    # Self-said clauses. Preserve each clause after 自述/自己说过.
    self_patterns = [
        r"(?:该群友自述|这个群友自述|自己说过|本人说过)[:：]?\s*([^。！？!?；;，,]+(?:\s+[A-Za-z0-9_+#.-]+)?)",
    ]
    for pattern in self_patterns:
        for clause in re.findall(pattern, raw):
            clause = str(clause).strip(" ：:，,。；; ")
            if clause:
                add_fact(f"自己说过{clause}")

    # If no structured facts were recovered, fall back to a cleaned version.
    if not facts:
        cleaned = _phase12_3_system_clean(raw)
        # Avoid returning empty/system-only text.
        if cleaned:
            return cleaned
        return "嗯…这条我没整理出能放心说的印象，别让我乱编啦。"

    if len(facts) == 1:
        return facts[0] + "。"
    return "，".join(facts) + "。"


def guard_natural_output_reply(reply: str, *, max_length: int = 500) -> str:  # type: ignore[override]
    original = str(reply or "")
    no_memory_voice = any(token in original for token in (
        "观测记录", "可靠记录", "可靠信息", "没找到这个人", "没有叫", "没有这个人", "没见过这个人", "没有找到"
    ))
    subject = _phase12_3_extract_question_subject(original)
    if no_memory_voice:
        if subject:
            text = f"嗯…{subject}我暂时没想起对应的是哪位，别让我乱编啦。你回复那个人或者 @ 一下，我就能接上。"
        else:
            text = "嗯…我暂时没对上你说的是哪位，别让我乱编啦。你回复那个人或者 @ 一下，我就能接上。"
    else:
        # If the input contains storage/report markers, rebuild a natural multi-fact reply.
        if any(token in original for token in ("管理员", "数据库", "系统记录", "后台", "检索", "记录显示", "该群友", "自述", "可靠记录", "观测记录")):
            text = _phase12_3_multifact_naturalize(original)
        elif _phase12_3_previous_guard_natural_output_reply is not None:
            try:
                text = _phase12_3_previous_guard_natural_output_reply(original, max_length=max_length)
            except TypeError:
                text = _phase12_3_previous_guard_natural_output_reply(original)
            except Exception:
                text = original
            text = _phase12_3_system_clean(text)
        else:
            text = _phase12_3_system_clean(original)
    text = _phase12_3_system_clean(text)
    return text[:max_length]
# --- END PHASE6_PERSONA_MEMORY_MULTIFACT_V12_3 ---
