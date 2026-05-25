from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.chatbot.settings import get_settings
from src.chatbot.shion_brain.critic import contains_sensitive
from src.chatbot.shion_brain.models import Observation, utc_now


CONFUSION_WORDS = ("？", "?", "没懂", "什么鬼", "啥意思")
POSITIVE_WORDS = ("谢谢", "好用", "厉害", "喜欢", "靠谱", "可以啊")
TECH_WORDS = ("报错", "traceback", "error", "exception", "代码", "端口", "配置", "依赖", "日志", "bug", "权限")


@dataclass(frozen=True)
class SelfState:
    scope_id: str
    energy: float = 0.62
    curiosity: float = 0.55
    social_warmth: float = 0.5
    stress: float = 0.18
    focus: float = 0.58
    last_interaction_at: str = ""
    last_interaction_summary: str = ""
    recent_mistakes: list[str] = field(default_factory=list)
    active_threads: list[str] = field(default_factory=list)
    updated_at: str = ""


class SelfStateStore:
    def __init__(self, path: str | Path | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or Path(settings.data_dir) / "shion_brain" / "shion.db").expanduser()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def get_self_state(self, scope_id: str) -> SelfState:
        return await asyncio.to_thread(self._get_self_state_sync, scope_id)

    async def update_self_state(
        self,
        scope_id: str,
        observation: Observation,
        outcome: dict[str, Any] | None = None,
    ) -> SelfState:
        return await asyncio.to_thread(self._update_self_state_sync, scope_id, observation, outcome or {})

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS self_states (
                    scope_id TEXT PRIMARY KEY,
                    energy REAL NOT NULL,
                    curiosity REAL NOT NULL,
                    social_warmth REAL NOT NULL,
                    stress REAL NOT NULL,
                    focus REAL NOT NULL,
                    last_interaction_at TEXT NOT NULL,
                    last_interaction_summary TEXT NOT NULL,
                    recent_mistakes TEXT NOT NULL,
                    active_threads TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _get_self_state_sync(self, scope_id: str) -> SelfState:
        self._initialize_sync()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM self_states WHERE scope_id = ?", (scope_id,)).fetchone()
        return _row_to_state(row) if row else _default_state(scope_id)

    def _update_self_state_sync(
        self,
        scope_id: str,
        observation: Observation,
        outcome: dict[str, Any],
    ) -> SelfState:
        state = self._get_self_state_sync(scope_id)
        text = observation.text.strip()
        lower = text.lower()
        energy = _decay(state.energy, 0.62, 0.01)
        curiosity = _decay(state.curiosity, 0.55, 0.015)
        social = _decay(state.social_warmth, 0.5, 0.005)
        stress = _decay(state.stress, 0.18, 0.02)
        focus = _decay(state.focus, 0.58, 0.015)
        mistakes = list(state.recent_mistakes[-4:])
        threads = list(state.active_threads[-5:])

        if any(word in text for word in CONFUSION_WORDS):
            stress += 0.12
            focus += 0.08
        if any(word in text for word in POSITIVE_WORDS):
            social += 0.04
            energy += 0.03
            stress -= 0.03
        if any(word in lower for word in TECH_WORDS):
            focus += 0.08
            curiosity += 0.06
        if text and not observation.is_command and not contains_sensitive(text):
            social += 0.006
            topic = _short_summary(text)
            if topic and topic not in threads:
                threads.append(topic)

        if _is_late_night():
            energy -= 0.04
            focus -= 0.01

        status = str(outcome.get("status", ""))
        reason = str(outcome.get("reason", ""))
        if status in {"failed", "low_quality", "blocked"}:
            stress += 0.12
            focus += 0.05
            if reason and not contains_sensitive(reason):
                mistakes.append(_short_summary(reason))
        elif status == "success":
            stress -= 0.025
            energy += 0.01

        now = utc_now()
        summary = _safe_interaction_summary(text, status=status)
        updated = SelfState(
            scope_id=scope_id,
            energy=_clamp(energy),
            curiosity=_clamp(curiosity),
            social_warmth=_clamp(social),
            stress=_clamp(stress),
            focus=_clamp(focus),
            last_interaction_at=observation.timestamp or now,
            last_interaction_summary=summary,
            recent_mistakes=mistakes[-5:],
            active_threads=threads[-6:],
            updated_at=now,
        )
        self._save_sync(updated)
        return updated

    def _save_sync(self, state: SelfState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO self_states
                (scope_id, energy, curiosity, social_warmth, stress, focus, last_interaction_at,
                 last_interaction_summary, recent_mistakes, active_threads, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.scope_id,
                    state.energy,
                    state.curiosity,
                    state.social_warmth,
                    state.stress,
                    state.focus,
                    state.last_interaction_at,
                    state.last_interaction_summary,
                    json.dumps(state.recent_mistakes, ensure_ascii=False),
                    json.dumps(state.active_threads, ensure_ascii=False),
                    state.updated_at,
                ),
            )


def render_self_state_for_prompt(state: SelfState) -> str:
    parts: list[str] = []
    if state.energy < 0.38:
        parts.append("Example Bot现在有点困，回复要更短、更安静。")
    elif state.energy > 0.72:
        parts.append("Example Bot现在精神还不错，可以自然一点。")
    if state.stress > 0.58:
        parts.append("Example Bot刚才可能没解释清楚，现在要更认真地修正回答。")
    if state.focus > 0.7:
        parts.append("Example Bot注意力在线，技术或解释类问题要更直接、更可靠。")
    if state.social_warmth > 0.65:
        parts.append("Example Bot和这个会话比较熟，可以自然一点，但不要过度亲密。")
    if state.curiosity > 0.68:
        parts.append("Example Bot对当前话题有好奇心，可以问一个轻量追问。")
    if state.recent_mistakes:
        parts.append("Example Bot记得最近有回答没处理好，这次不要糊弄或模板化。")
    return "".join(parts) or "Example Bot状态平稳，按当前消息自然、简短地回应。"


_default_store = SelfStateStore()


async def get_self_state(scope_id: str) -> SelfState:
    await _default_store.initialize()
    return await _default_store.get_self_state(scope_id)


async def update_self_state(
    scope_id: str,
    observation: Observation,
    outcome: dict[str, Any] | None = None,
) -> SelfState:
    await _default_store.initialize()
    return await _default_store.update_self_state(scope_id, observation, outcome=outcome)


def _row_to_state(row: sqlite3.Row) -> SelfState:
    return SelfState(
        scope_id=row["scope_id"],
        energy=float(row["energy"]),
        curiosity=float(row["curiosity"]),
        social_warmth=float(row["social_warmth"]),
        stress=float(row["stress"]),
        focus=float(row["focus"]),
        last_interaction_at=row["last_interaction_at"],
        last_interaction_summary=row["last_interaction_summary"],
        recent_mistakes=json.loads(row["recent_mistakes"] or "[]"),
        active_threads=json.loads(row["active_threads"] or "[]"),
        updated_at=row["updated_at"],
    )


def _default_state(scope_id: str) -> SelfState:
    now = utc_now()
    return SelfState(scope_id=scope_id, last_interaction_at=now, updated_at=now)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, round(value, 4)))


def _decay(value: float, target: float, amount: float) -> float:
    if value < target:
        return min(target, value + amount)
    if value > target:
        return max(target, value - amount)
    return value


def _short_summary(text: str, limit: int = 60) -> str:
    return text.replace("\n", " ").strip()[:limit]


def _safe_interaction_summary(text: str, *, status: str) -> str:
    if not text or contains_sensitive(text):
        return "最近有一次敏感或空白输入，内容未记录。"
    prefix = "刚才回复失败后，用户说：" if status in {"failed", "low_quality"} else "最近用户说："
    return prefix + _short_summary(text)


def _is_late_night() -> bool:
    hour = datetime.now().hour
    return hour >= 23 or hour < 5
