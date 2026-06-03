from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardDecision:
    text: str
    redacted: bool
    reasons: tuple[str, ...]
    audience: str


class OutputGuard:
    INTERNAL_ID_RE = re.compile(
        r"\b(?:QQ|qq|uid|UID|user_id|internal_user_key|account_id)\s*[:：=]?\s*\d{5,12}\b|\b\d{6,12}\b"
    )
    INTERNAL_ASSIGN_RE = re.compile(
        r"\b(?:user_id|uid|UID|internal_user_key|account_id|source_type|confidence|audit)\s*[:：=]\s*[\w.\-]+",
        re.I,
    )
    INTERNAL_TERMS = (
        "数据库",
        "后台",
        "source_type",
        "confidence",
        "audit",
        "审计",
        "user_id",
        "internal_user_key",
        "account_id",
        "QQ号",
        "QQ",
    )

    def guard(self, reply: str, audience: str = "public") -> GuardDecision:
        clean = str(reply or "")
        normalized_audience = str(audience or "public")
        if normalized_audience == "admin":
            return GuardDecision(clean.strip(), False, (), normalized_audience)

        reasons: list[str] = []
        next_text, count = self.INTERNAL_ASSIGN_RE.subn("[内部字段已隐藏]", clean)
        if count:
            reasons.append("internal_field")
        clean = next_text

        next_text, count = self.INTERNAL_ID_RE.subn("[内部ID已隐藏]", clean)
        if count:
            reasons.append("internal_id")
        clean = next_text

        for term in self.INTERNAL_TERMS:
            if term in clean:
                reasons.append("internal_term")
                clean = clean.replace(term, "")

        clean = re.sub(r"\s{2,}", " ", clean).strip()
        return GuardDecision(clean, bool(reasons), tuple(dict.fromkeys(reasons)), normalized_audience)

    def guard_reply(self, reply: str, audience: str = "public") -> str:
        return self.guard(reply, audience).text
