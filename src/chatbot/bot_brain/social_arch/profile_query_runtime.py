from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.chatbot.bot_brain.memory_decision_frame import build_memory_decision_frame
from src.chatbot.bot_brain.prompting.persona_context import (
    InternalTrace,
    RenderableFact,
    RenderableFactBundle,
    SafePersonaContext,
    bundle_to_safe_context,
    sanitize_persona_text,
)
from src.chatbot.bot_brain.social_arch.identity_facade import SocialIdentityFacade
from src.chatbot.bot_brain.social_cognition.alias_name_index import (
    iter_alias_name_candidates,
    is_label_like,
    normalize_label_key,
)
from src.chatbot.bot_brain.social_cognition.conversation_context import is_pronoun_or_reply_query
from src.chatbot.bot_brain.social_cognition.extractor import get_mentioned_user_ids


@dataclass(frozen=True)
class ProfileRuntimeResult:
    handled: bool
    reply: str = ""
    context: SafePersonaContext | None = None
    reason: str = ""
    candidate_labels: tuple[str, ...] = ()


FIXED_TEMPLATE_PREFIXES = ("嗯，我对上了", "嗯…我对上了", "我印象里", "通常被叫作")
INTERNAL_WORD_RE = re.compile(
    r"(QQ|uid|user_id|internal_user_key|memory_id|source_type|confidence|audit|数据库|后台|ResolvedTargetUserId|ProfileQueryAnswerContract)",
    re.I,
)


class ProfileQueryRuntime:
    """Partial runtime cutover for profile/alias queries.

    This path resolves identity before reading memories. It uses the typed
    alias/display-name bridge and never treats arbitrary memory body substrings
    as identity evidence.
    """

    def __init__(self, store: Any, *, identity_facade: SocialIdentityFacade | None = None) -> None:
        self.store = store
        self.identity_facade = identity_facade or SocialIdentityFacade(legacy_store=store)

    def answer(self, observation: Any, *, max_length: int = 420) -> ProfileRuntimeResult:
        frame = build_memory_decision_frame(observation)
        if frame.intent == "bot_self_query":
            return ProfileRuntimeResult(False, reason="bot_self_query")
        if not frame.search_memory and not frame.routing.get("block_normal_llm_when_handled"):
            return ProfileRuntimeResult(False, reason="not_profile_query")

        aliases = tuple(str(x).strip() for x in (frame.target.alias_terms or frame.memory_query.get("terms") or ()) if str(x).strip())
        target_id = str(frame.target.user_id or frame.memory_query.get("user_id") or "").strip()
        hard_mention = self._single_non_bot_mention(observation)
        if hard_mention and is_pronoun_or_reply_query(str(getattr(observation, "text", "") or "")):
            target_id = hard_mention

        if not target_id and aliases:
            alias_term = _normalize_alias_query_term(aliases[0])
            matched = self._resolve_active_typed_alias(alias_term, scope_id=str(frame.memory_query.get("scope_id") or ""))
            if len(matched) > 1:
                labels = self._candidate_labels(tuple(matched))
                return self._ambiguous(alias_term, labels, max_length=max_length)
            if not matched:
                return self._not_found(alias_term, max_length=max_length)
            target_id = matched[0]
            aliases = (alias_term,)

        if not target_id and frame.intent == "sender_self_query":
            resolved = self.identity_facade.resolve_sender(observation)
            if resolved.result.resolved:
                target_id = str(resolved.result.identity_id)

        if not target_id:
            return ProfileRuntimeResult(False, reason="unresolved_target")

        bundle = self._bundle_for(target_id, matched_alias=aliases[0] if aliases else "")
        if not bundle.aliases and not bundle.facts:
            return ProfileRuntimeResult(False, reason="no_profile_facts")
        trace = InternalTrace(target_identity_id=target_id, matched_by="profile_query_runtime")
        context = bundle_to_safe_context(bundle, trace=trace)
        reply = self._reply_from_bundle(bundle, query_text=str(getattr(observation, "text", "") or ""))
        reply = sanitize_persona_text(reply)
        if any(reply.startswith(prefix) for prefix in FIXED_TEMPLATE_PREFIXES) or INTERNAL_WORD_RE.search(reply):
            reply = self._fallback_from_bundle(bundle)
        return ProfileRuntimeResult(True, reply=reply[:max_length], context=context, reason="runtime_profile_query")

    def _bundle_for(self, identity_id: str, *, matched_alias: str = "") -> RenderableFactBundle:
        alias_values = self._aliases_for(identity_id)
        label = _first_label([matched_alias, *alias_values]) or "这位群友"
        facts: list[RenderableFact] = []
        for row in self._memories_for(identity_id):
            value = _safe_fact_text(str(row.get("memory_text") or row.get("value") or ""))
            if value and value not in {fact.value_text for fact in facts}:
                facts.append(RenderableFact(str(row.get("predicate") or "profile"), value, "public_summary"))
        return RenderableFactBundle(
            target_label=label,
            aliases=tuple(alias_values[:8]),
            facts=tuple(facts[:8]),
            uncertainty="confirmed" if facts or alias_values else "unknown",
            forbidden_fields=("QQ", "uid", "user_id", "internal_user_key", "memory_id", "source_type", "confidence", "audit"),
        )

    def _reply_from_bundle(self, bundle: RenderableFactBundle, *, query_text: str) -> str:
        aliases = [a for a in bundle.aliases if a and a != bundle.target_label]
        asks_aliases = bool(re.search(r"(又叫什么|还叫什么|别名|昵称|叫啥|叫什么)", query_text))
        if asks_aliases:
            names = [bundle.target_label, *aliases]
            if names:
                return "这个群友可以叫" + "、".join(dict.fromkeys(names[:6])) + "。"
            return "这个群友暂时没有更多可用称呼。"
        parts: list[str] = []
        if bundle.target_label:
            parts.append(f"这是群里可以叫“{bundle.target_label}”的群友")
        if aliases:
            parts.append("也可以叫" + "、".join(aliases[:3]))
        fact_texts = [fact.value_text.rstrip("。") for fact in bundle.facts if fact.value_text]
        if fact_texts:
            parts.append("记得的长期印象是：" + "；".join(dict.fromkeys(fact_texts[:4])))
        elif not parts:
            parts.append("这个群友我暂时还没积累到稳定印象")
        return "，".join(parts) + "。"

    def _fallback_from_bundle(self, bundle: RenderableFactBundle) -> str:
        if bundle.target_label:
            return f"这个群友可以叫“{bundle.target_label}”。"
        return "这个群友我暂时还没积累到稳定印象。"

    def _not_found(self, term: str, *, max_length: int) -> ProfileRuntimeResult:
        reply = sanitize_persona_text(f"暂时没找到叫“{term}”的群友；需要更明确的称呼或直接 @ 对方。")
        return ProfileRuntimeResult(True, reply=reply[:max_length], reason="not_found")

    def _ambiguous(self, term: str, labels: tuple[str, ...], *, max_length: int) -> ProfileRuntimeResult:
        suffix = "、".join(labels[:5]) if labels else "不止一位候选"
        reply = sanitize_persona_text(f"叫“{term}”的候选不唯一：{suffix}。需要你再明确一下。")
        return ProfileRuntimeResult(True, reply=reply[:max_length], reason="ambiguous_alias", candidate_labels=labels)

    def _aliases_for(self, identity_id: str) -> list[str]:
        values: list[str] = []
        try:
            for candidate in iter_alias_name_candidates(self.store):
                if candidate.user_id == identity_id and candidate.active and _safe_public_label(candidate.label):
                    values.append(candidate.label)
        except Exception:
            pass
        return list(dict.fromkeys(values))

    def _resolve_active_typed_alias(self, alias_text: str, *, scope_id: str = "") -> list[str]:
        key = normalize_label_key(alias_text)
        scope = str(scope_id or "").strip()
        has_typed_projection = self._has_any_typed_alias_memory(key, scope_id=scope)
        ids: list[str] = []
        try:
            for candidate in iter_alias_name_candidates(self.store):
                if candidate.label_key != key or not candidate.active:
                    continue
                if scope and candidate.group_id and candidate.group_id not in {scope, f"group:{scope}"}:
                    continue
                # Social-users display_name/aliases and typed active memory
                # rows are the only legacy bridge inputs allowed here.
                if candidate.reason == "social_users.aliases" and has_typed_projection:
                    continue
                if candidate.reason not in {"typed_social_memory", "social_users.aliases"} and candidate.label_type != "display_name":
                    continue
                if candidate.user_id not in ids:
                    ids.append(candidate.user_id)
        except Exception:
            return []
        return ids

    def _has_any_typed_alias_memory(self, alias_key: str, *, scope_id: str = "") -> bool:
        try:
            self.store.initialize()
            with self.store.connect() as conn:
                rows = conn.execute("SELECT * FROM social_memories").fetchall()
        except Exception:
            return False
        for row in rows:
            data = dict(row)
            scope = str(data.get("scope_id") or "").strip()
            if scope_id and scope and scope not in {scope_id, f"group:{scope_id}"}:
                continue
            predicate = str(data.get("predicate") or data.get("relation") or "").casefold()
            tags = str(data.get("tags_json") or "")
            if not (predicate in {"alias", "nickname", "display_name", "name", "称呼", "昵称", "外号"} or any(t in tags for t in ("alias", "nickname", "display_name", "admin_confirmed", "称呼", "昵称", "外号"))):
                continue
            haystacks = (
                str(data.get("value") or ""),
                str(data.get("object") or ""),
                str(data.get("memory_text") or ""),
                str(data.get("raw_evidence") or ""),
            )
            if any(normalize_label_key(alias_key) == normalize_label_key(text) or normalize_label_key(alias_key) in normalize_label_key(text) for text in haystacks):
                return True
        return False

    def _candidate_labels(self, identity_ids: tuple[str, ...]) -> tuple[str, ...]:
        labels: list[str] = []
        for identity_id in identity_ids:
            aliases = self._aliases_for(identity_id)
            labels.append(_first_label(aliases) or "一位群友")
        return tuple(labels)

    def _memories_for(self, identity_id: str) -> list[dict[str, Any]]:
        try:
            return [dict(row) for row in self.store.memories_for_user(identity_id, limit=8)]
        except Exception:
            return []

    @staticmethod
    def _single_non_bot_mention(observation: Any) -> str:
        features = getattr(observation, "features", {}) or {}
        bot_ids = {str(features.get(k) or "") for k in ("bot_id", "self_id", "bot_self_id")}
        sender = str(getattr(observation, "sender_id", "") or getattr(observation, "user_id", "") or "")
        targets = [uid for uid in get_mentioned_user_ids(observation) if uid and uid != sender and uid not in bot_ids]
        return targets[0] if len(targets) == 1 else ""


def _first_label(values: list[str] | tuple[str, ...]) -> str:
    for value in values:
        if value and _safe_public_label(value):
            return value
    return ""


def _safe_public_label(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text and is_label_like(text, max_len=20) and not re.search(r"\d{5,12}", text))


def _normalize_alias_query_term(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(又|还)$", "", text).strip()
    return text or str(value or "").strip()


def _safe_fact_text(text: str) -> str:
    raw = sanitize_persona_text(str(text or ""))
    raw = re.sub(r"^(该群友|这个群友|这个人)?自述[:：]?", "", raw).strip()
    raw = raw.replace("该群友", "这个群友").replace("管理员确认", "")
    raw = re.sub(r"\s+", " ", raw).strip(" ，,。；;：:")
    if not raw or INTERNAL_WORD_RE.search(raw):
        return ""
    return raw + ("。" if not raw.endswith(("。", "！", "？")) else "")
