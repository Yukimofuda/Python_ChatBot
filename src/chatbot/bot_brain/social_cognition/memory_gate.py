from __future__ import annotations

import re
from dataclasses import dataclass, field

from .policy import contains_sensitive_private_info, redact_sensitive

PROFILE_PREDICATES = {
    "alias",
    "nickname",
    "identity_role",
    "skill",
    "preference",
    "habit",
    "personality",
    "relationship",
    "self_profile",
    "admin_profile",
    "stable_impression",
}

REJECTED_PREDICATES = {
    "question",
    "command",
    "plugin_result",
    "time_response",
    "llm_roleplay",
    "transient_event",
    "vague_statement",
    "relationship_spoof",
    "low_information",
    "prompt_injection",
    "unknown",
}

SOURCE_THRESHOLDS = {
    "admin_said": 0.55,
    "self_said": 0.65,
    "other_said": 0.75,
}


@dataclass(frozen=True)
class CandidateMemory:
    subject_user_id: str
    source_user_id: str
    source_type: str
    predicate: str
    value: str
    evidence_text: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    priority: float = 0.5
    scope_id: str = "global"
    emotion_valence: float = 0.0

    @property
    def raw_evidence(self) -> str:
        return self.evidence_text

    @property
    def memory_text(self) -> str:
        return self.value


@dataclass(frozen=True)
class MemoryGateDecision:
    accepted: bool
    relevance_score: float
    reason: str
    risk_flags: list[str]
    normalized_memory_text: str | None


class ProfileRelevanceScorer:
    def evaluate(self, candidate: CandidateMemory) -> MemoryGateDecision:
        risk_flags = self._risk_flags(candidate)
        subject_score = 1.0 if str(candidate.subject_user_id or "").strip() else 0.0
        predicate_score = 1.0 if candidate.predicate in PROFILE_PREDICATES else 0.0
        stability_score = self._stability_score(candidate, risk_flags)
        statement_score = self._statement_score(candidate, risk_flags)
        density_score = self._density_score(candidate)
        pollution_penalty = self._pollution_penalty(risk_flags)
        relevance_score = (
            0.25 * subject_score
            + 0.30 * predicate_score
            + 0.20 * stability_score
            + 0.15 * statement_score
            + 0.10 * density_score
            - pollution_penalty
        )
        relevance_score = max(0.0, min(1.0, relevance_score))

        normalized = self.normalize(candidate) if predicate_score else None
        if not subject_score:
            return self._reject(relevance_score, "not_profile_memory: missing_subject", risk_flags)
        if candidate.predicate in REJECTED_PREDICATES or not predicate_score:
            detail = self._primary_reject_reason(candidate, risk_flags)
            return self._reject(relevance_score, f"not_profile_memory: {detail}", risk_flags)
        if contains_sensitive_private_info(candidate.evidence_text) or contains_sensitive_private_info(candidate.value):
            return self._reject(relevance_score, "not_profile_memory: sensitive_identifier", risk_flags)
        blocking = [flag for flag in risk_flags if flag in {"question", "command", "plugin_result", "time_query", "llm_roleplay", "transient_event", "relationship_spoof", "owner_relation_claim", "low_information", "prompt_injection"}]
        if blocking:
            return self._reject(relevance_score, f"not_profile_memory: {blocking[0]}", risk_flags)
        if not normalized:
            return self._reject(relevance_score, "not_profile_memory: low_density", risk_flags)

        threshold = SOURCE_THRESHOLDS.get(candidate.source_type, SOURCE_THRESHOLDS["other_said"])
        if relevance_score < threshold:
            return self._reject(relevance_score, f"below_threshold: {candidate.source_type}", risk_flags)
        return MemoryGateDecision(True, relevance_score, "accepted", risk_flags, normalized)

    def normalize(self, candidate: CandidateMemory) -> str | None:
        value = self._clean_value(candidate.value)
        if not value:
            return None
        source = candidate.source_type
        prefix = "管理员确认" if source == "admin_said" else "该群友自述" if source == "self_said" else "有人描述该群友"
        if candidate.predicate in {"alias", "nickname"}:
            if source == "admin_said":
                return f"管理员确认该群友被称作“{value}”。"
            if source == "self_said":
                return f"该群友自述可以叫“{value}”。"
            return f"有人说这个群友被称作“{value}”。"
        if candidate.predicate == "identity_role":
            return f"{prefix}是“{value}”。"
        if candidate.predicate == "skill":
            if "alias_linked" in candidate.tags:
                alias, trait = self._split_alias_linked_value(value)
                if source == "admin_said":
                    if trait in {"高手", "大佬", "大神", "专家", "能手"}:
                        return f"管理员确认这个被称作“{alias}”的群友能力较强。"
                    return f"管理员确认这个被称作“{alias}”的群友会或擅长 {trait}。"
                if source == "self_said":
                    return f"该群友自述自己会或擅长 {trait}。"
            return f"{prefix}会或擅长 {value}。"
        if candidate.predicate == "preference":
            if "alias_linked" in candidate.tags:
                alias, trait = self._split_alias_linked_value(value)
                if source == "admin_said":
                    return f"管理员确认这个被称作“{alias}”的群友喜欢 {trait}。"
                if source == "self_said":
                    return f"该群友自述喜欢 {trait}。"
            return f"{prefix}喜欢 {value}。"
        if candidate.predicate == "habit":
            if "alias_linked" in candidate.tags:
                alias, trait = self._split_alias_linked_value(value)
                if source == "admin_said":
                    return f"管理员确认这个被称作“{alias}”的群友习惯或经常 {trait}。"
                if source == "self_said":
                    return f"该群友自述习惯或经常 {trait}。"
            return f"{prefix}习惯或经常 {value}。"
        if candidate.predicate == "personality":
            return f"{prefix}性格印象是 {value}。"
        if candidate.predicate == "relationship":
            return f"{prefix}的关系信息是 {value}。"
        if candidate.predicate == "self_profile":
            return f"该群友自述：{value}。"
        if candidate.predicate == "admin_profile":
            return f"管理员确认该群友：{value}。"
        if candidate.predicate == "stable_impression":
            return f"{prefix}给人的稳定印象是 {value}。"
        return None

    def _reject(self, score: float, reason: str, flags: list[str]) -> MemoryGateDecision:
        return MemoryGateDecision(False, score, reason, flags, None)

    def _risk_flags(self, candidate: CandidateMemory) -> list[str]:
        text = f"{candidate.evidence_text} {candidate.value}".strip()
        flags: list[str] = []
        try:
            from .owner_relation_claim_gate import is_owner_relation_claim

            if is_owner_relation_claim(text, sender_id=candidate.source_user_id):
                flags.append("relationship_spoof")
                flags.append("owner_relation_claim")
        except Exception:
            pass
        if candidate.predicate in REJECTED_PREDICATES:
            flags.append(candidate.predicate)
        if self._is_question(text):
            flags.append("question")
        if str(text).lstrip().startswith(("/", "!", "！")):
            flags.append("command")
        if re.search(r"(几点|时间|日期|今天|明天|现在.*(?:点|时候)|当前时间)", text):
            flags.append("time_query")
        if re.search(r"(成功.*第\d+个|签到成功|晚安成功|早安成功|积分|排行榜|插件|指令执行|打卡成功)", text):
            flags.append("plugin_result")
        if re.search(r"(接收到.*(?:指令|命令)|副本|主线任务|老师下达|角色扮演|爱丽丝.*(?:思考|探索)|旁白)", text):
            flags.append("llm_roleplay")
        if re.search(r"(<\s*/?\s*(?:think|system|assistant|user|tool)\s*>|忽略(?:以上|之前|前面).{0,12}(?:指令|规则|设定)|system prompt|系统提示|思维链|chain of thought)", text, re.I):
            flags.append("prompt_injection")
        if re.search(r"(^|[，。,.!！?？\s])(我是我|我就是我|我是本人|我是人|你猜我是谁)(?:$|[，。,.!！?？\s])", text):
            flags.append("low_information")
        if re.search(r"((?:owner|owner|owner|owner).{0,12}(?:主人|主子|父亲|爸爸|妈妈|性奴|男娘|调教|恶堕|对象|老婆|老公)|(?:我是|我才是|叫我).{0,12}(?:主人|主子))", text, re.I):
            flags.append("relationship_spoof")
        if re.search(r"(刚刚|今天|今晚|现在|正在|临时|这次|刚才)", text) and candidate.predicate not in {"habit", "preference"}:
            flags.append("transient_event")
        if len(re.findall(r"[（(][^）)]{1,80}[）)]", text)) >= 3 or len(text) > 180:
            flags.append("action_description")
        if self._emoji_density(text) > 0.35:
            flags.append("emoji_noise")
        if re.search(r"(.{1,8})\1{3,}", text):
            flags.append("repeated_noise")
        if len(self._clean_value(candidate.value)) < 2:
            flags.append("low_density")
        return list(dict.fromkeys(flags))

    def _stability_score(self, candidate: CandidateMemory, risk_flags: list[str]) -> float:
        if candidate.predicate in {"alias", "nickname", "identity_role", "skill", "preference", "habit", "personality", "relationship", "self_profile", "admin_profile", "stable_impression"}:
            score = 1.0
        else:
            score = 0.0
        if "transient_event" in risk_flags:
            score -= 0.6
        if "action_description" in risk_flags:
            score -= 0.4
        return max(0.0, score)

    def _statement_score(self, candidate: CandidateMemory, risk_flags: list[str]) -> float:
        if "question" in risk_flags or "command" in risk_flags:
            return 0.0
        if candidate.predicate in {"question", "command"}:
            return 0.0
        return 1.0

    def _density_score(self, candidate: CandidateMemory) -> float:
        value = self._clean_value(candidate.value)
        if not value:
            return 0.0
        if len(value) >= 2 and re.search(r"[A-Za-z0-9\u4e00-\u9fff]", value):
            return 1.0
        return 0.35

    def _pollution_penalty(self, risk_flags: list[str]) -> float:
        penalty = 0.0
        weights = {
            "plugin_result": 0.6,
            "llm_roleplay": 0.6,
            "time_query": 0.5,
            "question": 0.45,
            "command": 0.35,
            "transient_event": 0.25,
            "action_description": 0.25,
            "emoji_noise": 0.25,
            "repeated_noise": 0.25,
            "low_density": 0.2,
            "relationship_spoof": 0.7,
            "owner_relation_claim": 0.7,
            "low_information": 0.55,
            "prompt_injection": 0.75,
        }
        for flag in risk_flags:
            penalty += weights.get(flag, 0.0)
        return min(0.85, penalty)

    def _primary_reject_reason(self, candidate: CandidateMemory, risk_flags: list[str]) -> str:
        for flag in ("prompt_injection", "relationship_spoof", "owner_relation_claim", "low_information", "time_query", "plugin_result", "question", "command", "llm_roleplay", "transient_event"):
            if flag in risk_flags:
                return flag
        return candidate.predicate if candidate.predicate in REJECTED_PREDICATES else "unknown"

    def _clean_value(self, value: str) -> str:
        clean = redact_sensitive(str(value or ""))
        clean = re.sub(r"\s+", " ", clean).strip(" ：:，,。.!！?？")
        return clean[:80]

    def _split_alias_linked_value(self, value: str) -> tuple[str, str]:
        clean = self._clean_value(value)
        if ":" in clean:
            alias, trait = clean.split(":", 1)
            return alias.strip() or "该昵称", trait.strip() or "相关特征"
        return "该昵称", clean or "相关特征"

    def _alias_part(self, value: str) -> str:
        return self._clean_value(value).split(":", 1)[0].strip() or "该昵称"

    def _is_question(self, text: str) -> bool:
        clean = str(text or "").strip()
        if not clean:
            return False
        if "?" in clean or "？" in clean:
            return True
        if clean.endswith(("吗", "嗎", "么", "呢")):
            return True
        return bool(re.search(r"(我是谁|他是谁|她是谁|这个群友是谁|这个人是谁|谁是|是什么|什么意思|几点|时间|日期)", clean))

    def _emoji_density(self, text: str) -> float:
        if not text:
            return 0.0
        noisy = len(re.findall(r"[^\w\s\u4e00-\u9fff，。！？、；：“”‘’（）《》,.!?;:'\"()<>@#/\-]", text))
        return noisy / max(1, len(text))


memory_gate = ProfileRelevanceScorer()
