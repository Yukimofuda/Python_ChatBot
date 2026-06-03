from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from src.chatbot.bot_brain.models import Observation


DEFAULT_BOT_NAMES = (
    "Bot",
    "generic bot",
    "Bot",
    "bot",
    "Bot",
    "Bot",
    "Bot",
    "Bot",
)

CQ_AT_RE = re.compile(r"\[CQ:at,qq=(?P<id>\d{5,12}|[A-Za-z0-9_\-]+)\]|\[at:qq=(?P<id2>\d{5,12}|[A-Za-z0-9_\-]+)\]")
REPLY_TEXT_RE = re.compile(r"\[回复消息\s*\[([^\](]{1,40})\((\d{5,12})\)\]", re.I)


@dataclass(frozen=True)
class MentionSpan:
    internal_key: str
    display_name: str = ""
    is_bot: bool = False
    source: str = "explicit_mention"


@dataclass(frozen=True)
class ReplyTarget:
    internal_key: str = ""
    display_name: str = ""
    text: str = ""


@dataclass(frozen=True)
class NormalizedObservation:
    sender_internal_key: str
    scope_id: str
    text: str
    raw_text: str
    mentioned_internal_keys: tuple[str, ...]
    mentions: tuple[MentionSpan, ...] = ()
    reply_target: ReplyTarget = ReplyTarget()
    bot_internal_keys: tuple[str, ...] = ()

    @property
    def non_bot_mentions(self) -> tuple[MentionSpan, ...]:
        return tuple(mention for mention in self.mentions if not mention.is_bot)


class MessageTextNormalizer:
    def normalize_text(
        self,
        text: str,
        *,
        bot_internal_keys: Iterable[str] = (),
        bot_names: Iterable[str] = (),
        mention_names: dict[str, str] | None = None,
    ) -> str:
        clean = str(text or "")
        bot_keys = {str(key) for key in bot_internal_keys if str(key)}
        names = tuple(dict.fromkeys([*DEFAULT_BOT_NAMES, *(str(name) for name in bot_names if str(name).strip())]))
        mention_names = {str(k): str(v) for k, v in (mention_names or {}).items() if str(k) and str(v).strip()}

        def replace_cq(match: re.Match[str]) -> str:
            key = str(match.group("id") or match.group("id2") or "")
            return " " if key in bot_keys else " "

        clean = CQ_AT_RE.sub(replace_cq, clean)
        clean = self._strip_leading_bot_names(clean, names)
        clean = self._strip_rendered_mentions(clean, mention_names, names)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip(" \t\r\n，,。")

    def _strip_leading_bot_names(self, text: str, bot_names: Iterable[str]) -> str:
        clean = str(text or "").strip()
        changed = True
        while changed:
            changed = False
            for name in sorted({n.strip() for n in bot_names if n.strip()}, key=len, reverse=True):
                patterns = (
                    rf"^@\s*{re.escape(name)}(?:\s+|[:：,，]+|$)",
                    rf"^{re.escape(name)}(?:\s+|[:：,，]+|$)",
                )
                for pattern in patterns:
                    next_text = re.sub(pattern, " ", clean, flags=re.I).strip()
                    if next_text != clean:
                        clean = next_text
                        changed = True
        return clean

    def _strip_rendered_mentions(self, text: str, mention_names: dict[str, str], bot_names: Iterable[str]) -> str:
        clean = str(text or "")
        names = [name for name in mention_names.values() if name]
        bot_name_set = {name.casefold() for name in bot_names if name}
        for name in sorted(names, key=len, reverse=True):
            if name.casefold() in bot_name_set:
                continue
            clean = re.sub(rf"@\s*{re.escape(name)}(?=\s|$|[，,。.!！?？:：])", " ", clean)
        return clean


class ObservationNormalizer:
    def __init__(self, text_normalizer: MessageTextNormalizer | None = None) -> None:
        self.text_normalizer = text_normalizer or MessageTextNormalizer()

    def normalize(self, observation: Observation) -> NormalizedObservation:
        features = _features(observation)
        bot_keys = _bot_internal_keys(observation)
        mention_names = _mentioned_display_names(observation)
        mentions = self._mentions(observation, bot_keys=bot_keys, mention_names=mention_names)
        scope = _scope_id(observation)
        raw = str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or "")
        text = self.text_normalizer.normalize_text(
            str(getattr(observation, "text", "") or raw),
            bot_internal_keys=bot_keys,
            bot_names=_bot_names(features),
            mention_names=mention_names,
        )
        return NormalizedObservation(
            sender_internal_key=str(getattr(observation, "sender_id", "") or getattr(observation, "user_id", "") or ""),
            scope_id=scope,
            text=text,
            raw_text=raw,
            mentioned_internal_keys=tuple(mention.internal_key for mention in mentions if not mention.is_bot),
            mentions=tuple(mentions),
            reply_target=_reply_target(observation),
            bot_internal_keys=tuple(sorted(bot_keys)),
        )

    def _mentions(self, observation: Observation, *, bot_keys: set[str], mention_names: dict[str, str]) -> list[MentionSpan]:
        ids: list[str] = []
        raw_lists = [
            getattr(observation, "mentioned_user_ids", None),
            _features(observation).get("mentioned_user_ids"),
            _features(observation).get("mentions"),
            _features(observation).get("at_user_ids"),
        ]
        for value in raw_lists:
            if isinstance(value, list):
                ids.extend(str(item) for item in value if str(item))
        raw = str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or "")
        for match in CQ_AT_RE.finditer(raw):
            key = str(match.group("id") or match.group("id2") or "")
            if key:
                ids.append(key)
        out: list[MentionSpan] = []
        seen: set[str] = set()
        for key in ids:
            if key in seen:
                continue
            seen.add(key)
            out.append(MentionSpan(key, mention_names.get(key, ""), key in bot_keys))
        return out


def strip_bot_rendered_text(text: str, *, bot_names: Iterable[str] = ()) -> str:
    return MessageTextNormalizer().normalize_text(text, bot_names=bot_names)


def _features(observation: Observation) -> dict[str, Any]:
    value = getattr(observation, "features", {}) or {}
    return value if isinstance(value, dict) else {}


def _scope_id(observation: Observation) -> str:
    features = _features(observation)
    raw = str(features.get("scope_id") or getattr(observation, "group_id", "") or "").strip()
    if not raw:
        return "global"
    return raw if raw.startswith("group:") else raw


def _bot_internal_keys(observation: Observation) -> set[str]:
    features = _features(observation)
    keys = {str(features.get(name) or "") for name in ("bot_id", "self_id", "bot_self_id")}
    keys.add(str(getattr(observation, "self_id", "") or ""))
    return {key for key in keys if key}


def _bot_names(features: dict[str, Any]) -> tuple[str, ...]:
    names = [str(features.get(name) or "") for name in ("bot_name", "self_name", "bot_display_name", "self_display_name")]
    return tuple(name for name in names if name.strip())


def _mentioned_display_names(observation: Observation) -> dict[str, str]:
    features = _features(observation)
    maps = (
        getattr(observation, "mentioned_display_names", None),
        getattr(observation, "mentioned_user_display_names", None),
        features.get("mentioned_display_names"),
        features.get("mentioned_user_display_names"),
    )
    merged: dict[str, str] = {}
    for mapping in maps:
        if isinstance(mapping, dict):
            for key, value in mapping.items():
                if str(key) and str(value).strip():
                    merged[str(key)] = str(value).strip()
    return merged


def _reply_target(observation: Observation) -> ReplyTarget:
    features = _features(observation)
    key = ""
    name = ""
    text = ""
    for field_name in ("reply_user_id", "replied_user_id", "reply_sender_id", "reply_to_user_id", "quoted_user_id", "source_user_id"):
        value = str(features.get(field_name) or "").strip()
        if value:
            key = value
            break
    for field_name in ("reply_sender_display_name", "replied_sender_display_name", "reply_display_name", "quoted_display_name", "reply_nickname"):
        value = str(features.get(field_name) or "").strip()
        if value:
            name = value
            break
    for field_name in ("reply_message_text", "replied_message_text", "quoted_text", "source_message_text"):
        value = str(features.get(field_name) or "").strip()
        if value:
            text = value
            break
    raw = str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or "")
    match = REPLY_TEXT_RE.search(raw)
    if match:
        name = name or match.group(1).strip()
        key = key or match.group(2).strip()
    return ReplyTarget(key, name, text)
