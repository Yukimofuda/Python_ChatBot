from __future__ import annotations

from dataclasses import dataclass
import re

from src.chatbot.shion_brain.models import Decision


FAILURE_REPLY = "还没想好说什么..."
SENSITIVE_BLOCK_REPLY = "这段里好像有密钥或 token，我先不直接发出来。"
BAD_PHRASES = (
    "我在旁边看了一眼，感觉这句有点可以接",
    "TODO",
    "undefined",
    "[object Object]",
    "As an AI language model",
    "作为一个AI语言模型",
    "作为一个 AI 语言模型",
    "作为一个AI",
    "亲亲您好",
    "尊敬的用户",
    "系统提示",
    "以下是详细说明",
    "专属萌系小助手",
)
HARD_IT_JOKES = ("segmentation fault", "root 权限", "daemon")
INSULTS = ("傻逼", "废物", "垃圾", "滚")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
SELF_EXPOSURE_RE = re.compile(
    r"(我.{0,12}(运行在|调用|接入|使用).{0,16}(NoneBot|NapCat|OneBot|API|接口|模型|prompt|系统提示)|"
    r"我是.{0,8}(bot|AI|模型|程序|工具)|"
    r"(NoneBot|NapCat|OneBot|prompt|system prompt|API key|Gemini API)|"
    r"Yuki.{0,12}(创造|唤醒|开发))",
    re.I,
)
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}|AIza[0-9A-Za-z_\-]{20,}|Authorization\s*[:=]\s*Bearer\s+\S+|"
    r"(api[_-]?key|token|secret|cookie|password|GEMINI_API_KEY|OPENAI_API_KEY|DASHSCOPE_API_KEY)\s*[:=]\s*[^\s]+|"
    r"webui\?token=[A-Za-z0-9_\-]+)",
    re.I,
)
PUNCT_ONLY_RE = re.compile(r"^[\s\W_。！？!?…,.，、~～-]+$")
TRUNCATED_RE = re.compile(r"(｡･$|\([^)]{1,12}$|[的了在是我你她他它和但而或把被给对向从到以与及又更最很还就都吗呢吧呀哦啊]$)")
STACK_RE = re.compile(r"(Traceback \(most recent call last\)|File \".+\", line \d+|HTTPStatusError|LLMProviderError)")


@dataclass(frozen=True)
class CriticVerdict:
    ok: bool
    text: str
    reason: str = ""
    rewrite_hint: str = ""
    replacement: str | None = None


class Critic:
    def check(self, text: str | None, *, decision: Decision) -> CriticVerdict:
        if text == FAILURE_REPLY:
            return CriticVerdict(True, text)
        if not text:
            return CriticVerdict(False, "", "empty reply", replacement=FAILURE_REPLY)
        clean = text.strip()
        if not clean:
            return CriticVerdict(False, clean, "empty reply", replacement=FAILURE_REPLY)
        if SECRET_RE.search(clean):
            return CriticVerdict(False, clean, "sensitive output", replacement=SENSITIVE_BLOCK_REPLY)
        if STACK_RE.search(clean):
            return CriticVerdict(False, clean, "stack trace leak", replacement=FAILURE_REPLY)
        if PUNCT_ONLY_RE.match(clean):
            return CriticVerdict(False, clean, "punctuation only", replacement=FAILURE_REPLY)
        if any(item.lower() in clean.lower() for item in BAD_PHRASES):
            return CriticVerdict(False, clean, "bad/template phrase", replacement=FAILURE_REPLY)
        if re.search(r"(?<![A-Za-z])(null|none)(?![A-Za-z])", clean, re.I):
            return CriticVerdict(False, clean, "null-ish reply", replacement=FAILURE_REPLY)
        if len(clean) < 6 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", clean):
            return CriticVerdict(False, clean, "too short without meaning", replacement=FAILURE_REPLY)
        if TRUNCATED_RE.search(clean) and not clean.endswith(("。", "？", "！", "...", "…", "♪", ")", "）")):
            return CriticVerdict(False, clean, "looks truncated", replacement=FAILURE_REPLY)
        if len(clean) > decision.max_length:
            return CriticVerdict(False, clean, "too long", "在自然句尾截短")
        lowered = clean.lower()
        if SELF_EXPOSURE_RE.search(clean):
            return CriticVerdict(False, clean, "self exposure", replacement=FAILURE_REPLY)
        if sum(1 for item in HARD_IT_JOKES if item in lowered) > 1:
            return CriticVerdict(False, clean, "too many hard IT jokes", replacement=FAILURE_REPLY)
        if any(item in clean for item in INSULTS):
            return CriticVerdict(False, clean, "insulting", replacement=FAILURE_REPLY)
        if decision.safety_level == "strict" and SECRET_RE.search(lowered):
            return CriticVerdict(False, clean, "sensitive echo", replacement=SENSITIVE_BLOCK_REPLY)
        if len(EMOJI_RE.findall(clean)) > 1:
            return CriticVerdict(False, clean, "too many emoji", replacement=FAILURE_REPLY)
        if clean.count("\n") >= 8:
            return CriticVerdict(False, clean, "too many lines", replacement=FAILURE_REPLY)
        return CriticVerdict(True, clean)


def contains_sensitive(text: str) -> bool:
    return bool(SECRET_RE.search(text))
