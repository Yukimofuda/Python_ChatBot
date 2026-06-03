from __future__ import annotations

from typing import Any


def summarize_profile(display_name: str, memories: list[dict[str, Any]]) -> str:
    name = display_name.strip() or "这个群友"
    if not memories:
        return f"{name} 目前只有出现记录，还没有足够可靠的印象。"
    lines = [f"{name} 的群友印象："]
    for memory in memories[:5]:
        source = str(memory.get("source_type") or "")
        confidence = float(memory.get("confidence") or 0.0)
        if source == "admin_said":
            source_hint = "管理员确认"
            certainty = "高可信"
        elif source == "self_said":
            source_hint = "自述"
            certainty = "高可信" if confidence >= 0.75 else "一般可信"
        elif source == "other_said":
            source_hint = "他人描述"
            certainty = "待确认"
        else:
            source_hint = source
            certainty = "高可信" if confidence >= 0.75 else "待确认" if confidence < 0.55 else "一般可信"
        lines.append(f"- [{certainty}/{source_hint}] {memory.get('memory_text', '')}")
    return "\n".join(lines)
